"""Share-link service.

Public objects are exposed only through opaque, revocable, expiring tokens.
The raw token is shown once at creation; only its SHA-256 hash is persisted.

The pure helpers (generate_token / hash_token / parse_expires_in) intentionally
depend only on the standard library so they can be unit-tested in isolation.
DB-touching helpers import models lazily.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from app.core.config import settings

if TYPE_CHECKING:  # avoid importing SQLAlchemy at module load
    import uuid
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.models.share import ShareLink
    from app.models.user import User

DEFAULT_EXPIRES_IN = "7d"
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


class ShareLinkGone(Exception):
    """Raised when a share link is missing, expired, or revoked."""


@dataclass(frozen=True)
class ResolvedShareLink:
    id: "uuid.UUID"
    bucket: str
    object_key: str


# --- pure helpers -----------------------------------------------------------

def generate_token() -> str:
    """A URL-safe, high-entropy opaque token (~43 chars)."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 hex digest used for at-rest storage and lookup."""
    return hashlib.sha256(token.encode()).hexdigest()


def _seconds_from(value: str | int | None) -> int | None:
    """Normalize an expires_in value to a positive number of seconds, or None
    for 'never'. Raises ValueError on malformed input."""
    if value is None:
        return None
    if isinstance(value, bool):  # bool is an int subclass; reject explicitly
        raise ValueError(f"Invalid expires_in: {value!r}")
    if isinstance(value, int):
        seconds = value
    else:
        v = value.strip().lower()
        if v == "":
            v = DEFAULT_EXPIRES_IN
        if v == "never":
            return None
        if v.isdigit():
            seconds = int(v)
        elif len(v) >= 2 and v[-1] in _UNIT_SECONDS and v[:-1].isdigit():
            seconds = int(v[:-1]) * _UNIT_SECONDS[v[-1]]
        else:
            raise ValueError(f"Invalid expires_in: {value!r}")
    if seconds <= 0:
        raise ValueError("expires_in must be a positive duration")
    return seconds


def parse_expires_in(value: str | int | None = None) -> datetime | None:
    """Resolve an expires_in shorthand ('1h'/'24h'/'7d'/'30d'), integer seconds,
    numeric string, '' (default 7d), or None/'never' into an absolute UTC
    expiry datetime, or None for links that never expire."""
    seconds = _seconds_from(value)
    if seconds is None:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


# --- DB-touching helpers ----------------------------------------------------

async def create_share_link(
    db: "AsyncSession",
    user: "User",
    bucket: str,
    object_key: str,
    expires_at: datetime | None,
) -> tuple["ShareLink", str]:
    """Create a share link. Returns (link, raw_token). The raw token is only
    available here — the DB stores its hash."""
    from app.models.share import ShareLink

    raw_token = generate_token()
    link = ShareLink(
        token_hash=hash_token(raw_token),
        bucket=bucket,
        object_key=object_key,
        created_by_user_id=user.id,
        created_by_email=user.email,
        expires_at=expires_at,
    )
    db.add(link)
    await db.flush()
    return link, raw_token


async def resolve_active_link(db: "AsyncSession", token: str) -> ResolvedShareLink:
    """Validate a link and increment one counter shard in a single statement."""
    from sqlalchemy import text

    now = datetime.now(timezone.utc)
    shard = secrets.randbelow(settings.SHARE_ACCESS_COUNTER_SHARDS)
    result = await db.execute(
        text(
            """
            WITH active_link AS (
                SELECT id, bucket, object_key
                FROM share_links
                WHERE token_hash = :token_hash
                  AND revoked IS FALSE
                  AND (expires_at IS NULL OR expires_at > :accessed_at)
            ), recorded_access AS (
                INSERT INTO share_link_access_counters (
                    share_link_id, shard, access_count, last_accessed_at
                )
                SELECT id, :shard, 1, :accessed_at
                FROM active_link
                ON CONFLICT (share_link_id, shard) DO UPDATE
                SET access_count = share_link_access_counters.access_count + 1,
                    last_accessed_at = EXCLUDED.last_accessed_at
                RETURNING share_link_id
            )
            SELECT active_link.id, active_link.bucket, active_link.object_key
            FROM active_link
            JOIN recorded_access
              ON recorded_access.share_link_id = active_link.id
            """
        ),
        {
            "token_hash": hash_token(token),
            "shard": shard,
            "accessed_at": now,
        },
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise ShareLinkGone()

    await db.commit()
    return ResolvedShareLink(
        id=row["id"],
        bucket=row["bucket"],
        object_key=row["object_key"],
    )


async def list_links(db: "AsyncSession", user: "User", bucket: str | None = None):
    """List share links visible to the user (own links; admins see all)."""
    from sqlalchemy import func, select
    from sqlalchemy.orm.attributes import set_committed_value
    from app.models.share import ShareLink, ShareLinkAccessCounter

    counter_totals = (
        select(
            ShareLinkAccessCounter.share_link_id.label("share_link_id"),
            func.sum(ShareLinkAccessCounter.access_count).label("access_count"),
            func.max(ShareLinkAccessCounter.last_accessed_at).label("last_accessed_at"),
        )
        .group_by(ShareLinkAccessCounter.share_link_id)
        .subquery()
    )
    stmt = (
        select(
            ShareLink,
            counter_totals.c.access_count,
            counter_totals.c.last_accessed_at,
        )
        .outerjoin(counter_totals, counter_totals.c.share_link_id == ShareLink.id)
        .order_by(ShareLink.created_at.desc())
        .execution_options(populate_existing=True)
    )
    if not user.is_admin:
        stmt = stmt.where(ShareLink.created_by_user_id == user.id)
    if bucket:
        stmt = stmt.where(ShareLink.bucket == bucket)
    result = await db.execute(stmt)
    links = []
    for link, sharded_count, sharded_last_accessed_at in result.all():
        set_committed_value(
            link,
            "access_count",
            link.access_count + int(sharded_count or 0),
        )
        if sharded_last_accessed_at is not None and (
            link.last_accessed_at is None
            or sharded_last_accessed_at > link.last_accessed_at
        ):
            set_committed_value(link, "last_accessed_at", sharded_last_accessed_at)
        links.append(link)
    return links


async def revoke_link(db: "AsyncSession", user: "User", link_id: "uuid.UUID") -> "ShareLink | None":
    """Revoke a link if the user owns it or is admin. Returns the link, or None
    if not found / not permitted."""
    from sqlalchemy import select
    from app.models.share import ShareLink

    result = await db.execute(select(ShareLink).where(ShareLink.id == link_id))
    link = result.scalar_one_or_none()
    if link is None:
        return None
    if not user.is_admin and link.created_by_user_id != user.id:
        return None
    if not link.revoked:
        link.revoked = True
        link.revoked_at = datetime.now(timezone.utc)
        await db.flush()
    return link
