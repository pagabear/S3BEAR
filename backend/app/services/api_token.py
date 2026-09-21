"""Personal access token (PAT) service.

A PAT authenticates as the user who created it and inherits that user's group
permissions — there are no separate token scopes. Tokens are opaque, prefixed
with ``s3bear_pat_``, stored only as a SHA-256 hash, optionally expiring, and
always revocable.

Pure helpers depend only on the standard library; DB helpers import models lazily.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uuid
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.models.api_token import ApiToken
    from app.models.user import User

PAT_PREFIX = "s3bear_pat_"
_LAST_USED_THROTTLE_SECONDS = 60


# --- pure helpers -----------------------------------------------------------

def generate_token() -> str:
    return PAT_PREFIX + secrets.token_urlsafe(32)


def looks_like_pat(token: str) -> bool:
    return token.startswith(PAT_PREFIX)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def token_prefix(token: str) -> str:
    """A short, human-identifiable head of the token for display in lists.
    Never returns enough to reconstruct the secret."""
    return token[: len(PAT_PREFIX) + 8]


def should_update_last_used(last_used_at: datetime | None) -> bool:
    """Throttle last_used_at writes so hot API traffic doesn't cause a DB write
    on every request."""
    if last_used_at is None:
        return True
    now = datetime.now(timezone.utc)
    if last_used_at.tzinfo is None:
        last_used_at = last_used_at.replace(tzinfo=timezone.utc)
    return (now - last_used_at).total_seconds() >= _LAST_USED_THROTTLE_SECONDS


# --- DB-touching helpers ----------------------------------------------------

async def create_token(
    db: "AsyncSession",
    user: "User",
    name: str,
    expires_at: datetime | None,
) -> tuple["ApiToken", str]:
    """Create a PAT. Returns (token_row, raw_token). The raw token is only
    available here."""
    from app.models.api_token import ApiToken

    raw = generate_token()
    row = ApiToken(
        user_id=user.id,
        name=name,
        token_hash=hash_token(raw),
        token_prefix=token_prefix(raw),
        expires_at=expires_at,
    )
    db.add(row)
    await db.flush()
    return row, raw


async def authenticate(db: "AsyncSession", raw_token: str) -> "User | None":
    """Resolve a raw PAT to its active user, or None if the token is unknown,
    revoked, expired, or the user is inactive. Updates last_used_at (throttled)."""
    from sqlalchemy import select
    from app.models.api_token import ApiToken
    from app.services.auth import load_active_user_with_permissions

    result = await db.execute(
        select(ApiToken).where(ApiToken.token_hash == hash_token(raw_token))
    )
    row = result.scalar_one_or_none()
    if row is None or row.revoked:
        return None
    now = datetime.now(timezone.utc)
    if row.expires_at is not None and row.expires_at <= now:
        return None

    user = await load_active_user_with_permissions(db, row.user_id)
    if user is None:
        return None

    if should_update_last_used(row.last_used_at):
        row.last_used_at = now
        await db.flush()
    return user


async def list_tokens(db: "AsyncSession", user: "User"):
    from sqlalchemy import select
    from app.models.api_token import ApiToken

    result = await db.execute(
        select(ApiToken)
        .where(ApiToken.user_id == user.id)
        .order_by(ApiToken.created_at.desc())
    )
    return list(result.scalars().all())


async def revoke_token(db: "AsyncSession", user: "User", token_id: "uuid.UUID") -> "ApiToken | None":
    """Revoke a token owned by the user (or any token, if the user is admin).
    Returns the token, or None if not found / not permitted."""
    from sqlalchemy import select
    from app.models.api_token import ApiToken

    result = await db.execute(select(ApiToken).where(ApiToken.id == token_id))
    row = result.scalar_one_or_none()
    if row is None:
        return None
    if not user.is_admin and row.user_id != user.id:
        return None
    if not row.revoked:
        row.revoked = True
        row.revoked_at = datetime.now(timezone.utc)
        await db.flush()
    return row
