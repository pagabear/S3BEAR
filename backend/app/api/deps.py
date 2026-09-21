import uuid
from typing import Annotated
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import User
from app.services import permissions

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Personal access tokens are opaque and prefixed; resolve them against the DB
    # before attempting JWT validation. A PAT acts as its owning user.
    from app.services import api_token as api_token_service

    if api_token_service.looks_like_pat(token):
        user = await api_token_service.authenticate(db, token)
        if user is None:
            raise credentials_exc
        return user

    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise credentials_exc
        user_id: str = payload.get("sub")
        if not user_id:
            raise credentials_exc
    except JWTError:
        raise credentials_exc

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_exc
    return user


async def require_admin(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return current_user


def ensure_bucket_permission(user: User, bucket_name: str, action: str) -> None:
    """Raise HTTP 403 unless `user` may perform `action` on `bucket_name`.

    The single imperative entry point for permission checks in request handlers.
    All matching logic (including the fnmatch hardening) lives in
    ``app.services.permissions``.
    """
    if not permissions.has_permission(user, bucket_name, action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"No '{action}' permission for bucket '{bucket_name}'",
        )


def require_bucket_permission(action: str):
    """Returns a FastAPI dependency that enforces `action` on the path's bucket."""
    if action not in permissions.ACTION_MAP:
        raise ValueError(f"Unknown action: {action}")

    async def checker(
        bucket_name: str,
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        ensure_bucket_permission(current_user, bucket_name, action)
        return current_user

    return checker
