from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.models.provider import StorageProvider, ManagedBucket
from app.models.user import User
from app.schemas.provider import (
    StorageProviderCreate, StorageProviderUpdate, StorageProviderRead,
    ProviderTestRequest, ProviderTestResult,
)
from app.services import s3 as s3_service
from app.services.provider_registry import reload_registry
from app.services.audit import log_audit, PROVIDER_CREATE, PROVIDER_UPDATE, PROVIDER_DELETE

router = APIRouter(prefix="/providers", tags=["providers"])


async def _bucket_counts(db: AsyncSession) -> dict[UUID, int]:
    rows = await db.execute(
        select(ManagedBucket.provider_id, func.count()).group_by(ManagedBucket.provider_id)
    )
    return {pid: n for pid, n in rows.all()}


def _to_read(p: StorageProvider, bucket_count: int) -> StorageProviderRead:
    return StorageProviderRead(
        id=p.id,
        name=p.name,
        provider_type=p.provider_type,
        access_key_id=p.access_key_id,
        region=p.region,
        endpoint_url=p.endpoint_url,
        presigned_base=p.presigned_base,
        use_ssl=p.use_ssl,
        is_default=p.is_default,
        has_secret=bool(p.secret_access_key),
        bucket_count=bucket_count,
        created_at=p.created_at,
    )


@router.get("", response_model=list[StorageProviderRead])
async def list_providers(
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    providers = (await db.execute(select(StorageProvider).order_by(StorageProvider.created_at))).scalars().all()
    counts = await _bucket_counts(db)
    return [_to_read(p, counts.get(p.id, 0)) for p in providers]


async def _clear_default(db: AsyncSession) -> None:
    rows = (await db.execute(select(StorageProvider).where(StorageProvider.is_default.is_(True)))).scalars().all()
    for r in rows:
        r.is_default = False


@router.post("", response_model=StorageProviderRead, status_code=201)
async def create_provider(
    body: StorageProviderCreate,
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    existing = (await db.execute(select(StorageProvider).where(StorageProvider.name == body.name))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"A provider named '{body.name}' already exists")

    cfg = {
        "access_key": body.access_key_id, "secret_key": body.secret_access_key,
        "region": body.region, "endpoint": body.endpoint_url, "presigned_base": body.presigned_base,
    }
    try:
        await s3_service.test_config(cfg)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Connection test failed: {str(e)[:200]}")

    # First provider is always the default; otherwise honor the request.
    provider_count = (await db.execute(select(func.count()).select_from(StorageProvider))).scalar_one()
    make_default = body.is_default or provider_count == 0
    if make_default:
        await _clear_default(db)

    provider = StorageProvider(
        name=body.name,
        provider_type=body.provider_type,
        access_key_id=body.access_key_id,
        secret_access_key=body.secret_access_key,
        region=body.region,
        endpoint_url=body.endpoint_url,
        presigned_base=body.presigned_base,
        use_ssl=body.use_ssl,
        is_default=make_default,
    )
    db.add(provider)
    await db.flush()
    await log_audit(db, admin, PROVIDER_CREATE, details={"name": body.name, "type": body.provider_type},
                    ip_address=request.client.host if request.client else None)
    await db.commit()
    await reload_registry(db)
    return _to_read(provider, 0)


@router.put("/{provider_id}", response_model=StorageProviderRead)
async def update_provider(
    provider_id: UUID,
    body: StorageProviderUpdate,
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    provider = (await db.execute(select(StorageProvider).where(StorageProvider.id == provider_id))).scalar_one_or_none()
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    if body.name is not None and body.name != provider.name:
        clash = (await db.execute(select(StorageProvider).where(StorageProvider.name == body.name))).scalar_one_or_none()
        if clash:
            raise HTTPException(status_code=409, detail=f"A provider named '{body.name}' already exists")

    # Resolve effective config for validation (new values fall back to stored ones).
    new_secret = body.secret_access_key if body.secret_access_key else provider.secret_access_key
    cfg = {
        "access_key": body.access_key_id if body.access_key_id is not None else provider.access_key_id,
        "secret_key": new_secret,
        "region": body.region if body.region is not None else provider.region,
        "endpoint": body.endpoint_url if body.endpoint_url is not None else provider.endpoint_url,
        "presigned_base": body.presigned_base if body.presigned_base is not None else provider.presigned_base,
    }
    try:
        await s3_service.test_config(cfg)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Connection test failed: {str(e)[:200]}")

    for field in ("name", "provider_type", "access_key_id", "region", "endpoint_url", "presigned_base", "use_ssl"):
        val = getattr(body, field)
        if val is not None:
            setattr(provider, field, val)
    if body.secret_access_key:
        provider.secret_access_key = body.secret_access_key
    if body.is_default is True and not provider.is_default:
        await _clear_default(db)
        provider.is_default = True

    await db.flush()
    counts = await _bucket_counts(db)
    await log_audit(db, admin, PROVIDER_UPDATE, details={"name": provider.name},
                    ip_address=request.client.host if request.client else None)
    await db.commit()
    await reload_registry(db)
    return _to_read(provider, counts.get(provider.id, 0))


@router.post("/{provider_id}/default", response_model=StorageProviderRead)
async def set_default_provider(
    provider_id: UUID,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    provider = (await db.execute(select(StorageProvider).where(StorageProvider.id == provider_id))).scalar_one_or_none()
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    await _clear_default(db)
    provider.is_default = True
    await db.commit()
    await reload_registry(db)
    counts = await _bucket_counts(db)
    return _to_read(provider, counts.get(provider.id, 0))


@router.delete("/{provider_id}", status_code=200)
async def delete_provider(
    provider_id: UUID,
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    provider = (await db.execute(select(StorageProvider).where(StorageProvider.id == provider_id))).scalar_one_or_none()
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    counts = await _bucket_counts(db)
    attached = counts.get(provider.id, 0)
    if attached:
        raise HTTPException(
            status_code=409,
            detail=f"Provider has {attached} bucket(s) attached. Delete or reassign them first.",
        )

    name = provider.name
    was_default = provider.is_default
    await db.delete(provider)
    await db.flush()

    # If we removed the default, promote another provider so routing keeps working.
    if was_default:
        remaining = (await db.execute(select(StorageProvider).order_by(StorageProvider.created_at))).scalars().first()
        if remaining:
            remaining.is_default = True

    await log_audit(db, admin, PROVIDER_DELETE, details={"name": name},
                    ip_address=request.client.host if request.client else None)
    await db.commit()
    await reload_registry(db)
    return {"deleted": str(provider_id)}


@router.post("/test", response_model=ProviderTestResult)
async def test_provider(
    body: ProviderTestRequest,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    secret = body.secret_access_key
    if not secret and body.id is not None:
        provider = (await db.execute(select(StorageProvider).where(StorageProvider.id == body.id))).scalar_one_or_none()
        if provider:
            secret = provider.secret_access_key
    if not secret:
        return ProviderTestResult(ok=False, error="Secret access key is required")

    cfg = {
        "access_key": body.access_key_id, "secret_key": secret, "region": body.region,
        "endpoint": body.endpoint_url, "presigned_base": body.presigned_base,
    }
    try:
        await s3_service.test_config(cfg)
    except Exception as e:  # noqa: BLE001
        return ProviderTestResult(ok=False, error=str(e)[:200])
    return ProviderTestResult(ok=True, error=None)
