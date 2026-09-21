import re
import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.models.settings import AppSetting
from app.models.provider import StorageProvider, ManagedBucket
from app.models.bucket_tag import BucketTag as BucketTagModel
from app.schemas.s3 import BucketInfo, BucketTag, BrowseResult, S3Object
from app.services import s3 as s3_service
from app.services.permissions import resolve_permissions as _resolve_permissions
from app.services.audit import log_audit, CREATE_BUCKET, DELETE_BUCKET

router = APIRouter(prefix="/buckets", tags=["buckets"])


_BUCKET_NAME_RE = re.compile(r'^[a-z0-9][a-z0-9.\-]{1,61}[a-z0-9]$')


class CreateBucketRequest(BaseModel):
    name: str
    quota_gb: float | None = None
    provider_id: str | None = None  # which storage provider serves this bucket
    tags: list[BucketTag] = []

    @field_validator("name")
    @classmethod
    def validate_bucket_name(cls, v: str) -> str:
        if not _BUCKET_NAME_RE.match(v):
            raise ValueError(
                "Invalid bucket name. Must be 3-63 characters, lowercase letters, numbers, dots and hyphens only."
            )
        if ".." in v:
            raise ValueError("Bucket name must not contain consecutive dots")
        return v


class SetTagsRequest(BaseModel):
    tags: list[BucketTag] = []


def _clean_tags(tags: list[BucketTag]) -> list[BucketTag]:
    """Drop blank keys and collapse duplicate keys (last one wins)."""
    seen: dict[str, str] = {}
    for t in tags:
        k = t.key.strip()
        if k:
            seen[k] = t.value.strip()
    return [BucketTag(key=k, value=v) for k, v in seen.items()]


async def _tags_for(db: AsyncSession, bucket_names: list[str]) -> dict[str, list[BucketTag]]:
    """Return {bucket_name: [BucketTag, ...]} for the given buckets."""
    if not bucket_names:
        return {}
    rows = (await db.execute(
        select(BucketTagModel).where(BucketTagModel.bucket_name.in_(bucket_names))
    )).scalars().all()
    out: dict[str, list[BucketTag]] = {}
    for r in rows:
        out.setdefault(r.bucket_name, []).append(BucketTag(key=r.key, value=r.value))
    return out


@router.get("", response_model=list[BucketInfo])
async def list_buckets(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    all_buckets = await s3_service.list_buckets()
    visible = [b for b in all_buckets if any(_resolve_permissions(current_user, b["name"]).values())]
    tags_by_bucket = await _tags_for(db, [b["name"] for b in visible])
    result = []
    for bucket in visible:
        perms = _resolve_permissions(current_user, bucket["name"])
        result.append(
            BucketInfo(
                name=bucket["name"],
                creation_date=bucket.get("creation_date"),
                provider_id=bucket.get("provider_id"),
                provider_name=bucket.get("provider_name"),
                tags=tags_by_bucket.get(bucket["name"], []),
                **perms,
            )
        )
    return result


@router.post("", status_code=201, responses={409: {"description": "Bucket already exists"}})
async def create_bucket(
    body: CreateBucketRequest,
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Resolve the target provider: explicit choice, else the default provider.
    provider: StorageProvider | None = None
    if body.provider_id:
        try:
            pid = uuid.UUID(body.provider_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid provider_id")
        provider = (await db.execute(select(StorageProvider).where(StorageProvider.id == pid))).scalar_one_or_none()
        if provider is None:
            raise HTTPException(status_code=404, detail="Provider not found")
    else:
        provider = (await db.execute(select(StorageProvider).where(StorageProvider.is_default == True))).scalar_one_or_none()  # noqa: E712

    # Bucket names are globally unique across s3BEAR so routing stays unambiguous.
    already = (await db.execute(select(ManagedBucket).where(ManagedBucket.name == body.name))).scalar_one_or_none()
    if already:
        raise HTTPException(status_code=409, detail=f"Bucket '{body.name}' already exists")

    try:
        await s3_service.create_bucket(body.name, provider_id=str(provider.id) if provider else None)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    if provider is not None:
        db.add(ManagedBucket(name=body.name, provider_id=provider.id))

    if body.quota_gb is not None:
        key = f"bucket_quota_gb:{body.name}"
        existing = await db.execute(select(AppSetting).where(AppSetting.key == key))
        row = existing.scalar_one_or_none()
        if row:
            row.value = str(body.quota_gb)
        else:
            db.add(AppSetting(key=key, value=str(body.quota_gb)))

    for t in _clean_tags(body.tags):
        db.add(BucketTagModel(bucket_name=body.name, key=t.key, value=t.value))

    await log_audit(db, admin, CREATE_BUCKET, bucket=body.name,
                    details={"quota_gb": body.quota_gb, "provider": provider.name if provider else None},
                    ip_address=request.client.host if request.client else None)
    await db.flush()
    if provider is not None:
        s3_service.register_bucket(body.name, str(provider.id))
    return {"name": body.name, "quota_gb": body.quota_gb,
            "provider_id": str(provider.id) if provider else None,
            "provider_name": provider.name if provider else None}


@router.delete("/{bucket_name}", status_code=200, responses={404: {"description": "Bucket not found"}, 409: {"description": "Bucket not empty"}})
async def delete_bucket(
    bucket_name: str,
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        await s3_service.delete_bucket(bucket_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    mb = (await db.execute(select(ManagedBucket).where(ManagedBucket.name == bucket_name))).scalar_one_or_none()
    if mb:
        await db.delete(mb)
    await db.execute(
        BucketTagModel.__table__.delete().where(BucketTagModel.bucket_name == bucket_name)
    )
    s3_service.unregister_bucket(bucket_name)

    await log_audit(db, admin, DELETE_BUCKET, bucket=bucket_name,
                    ip_address=request.client.host if request.client else None)
    return {"deleted": bucket_name}


@router.get("/tags/suggest")
async def suggest_tags(
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return {key: [distinct values...]} across all buckets, for autocomplete."""
    rows = (await db.execute(select(BucketTagModel))).scalars().all()
    suggest: dict[str, list[str]] = {}
    for r in rows:
        vals = suggest.setdefault(r.key, [])
        if r.value and r.value not in vals:
            vals.append(r.value)
    return suggest


@router.get("/{bucket_name}/tags", response_model=list[BucketTag])
async def get_bucket_tags(
    bucket_name: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    perms = _resolve_permissions(current_user, bucket_name)
    if not any(perms.values()):
        raise HTTPException(status_code=403, detail="No access to this bucket")
    return (await _tags_for(db, [bucket_name])).get(bucket_name, [])


@router.put("/{bucket_name}/tags", response_model=list[BucketTag])
async def set_bucket_tags(
    bucket_name: str,
    body: SetTagsRequest,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Replace the full tag set for a bucket."""
    await db.execute(
        BucketTagModel.__table__.delete().where(BucketTagModel.bucket_name == bucket_name)
    )
    cleaned = _clean_tags(body.tags)
    for t in cleaned:
        db.add(BucketTagModel(bucket_name=bucket_name, key=t.key, value=t.value))
    await db.flush()
    return cleaned


@router.get("/{bucket_name}/browse", response_model=BrowseResult, responses={403: {"description": "No list permission"}})
async def browse_bucket(
    bucket_name: str,
    current_user: Annotated[User, Depends(get_current_user)],
    prefix: Annotated[str, Query()] = "",
):
    perms = _resolve_permissions(current_user, bucket_name)
    if not perms["can_list"]:
        raise HTTPException(status_code=403, detail="No list permission for this bucket")

    data = await s3_service.list_objects(bucket=bucket_name, prefix=prefix)
    objects = [
        S3Object(
            key=obj["key"],
            size=obj["size"],
            last_modified=obj["last_modified"],
            etag=obj["etag"],
        )
        for obj in data["objects"]
    ]
    return BrowseResult(
        prefix=prefix,
        objects=objects,
        common_prefixes=data["common_prefixes"],
    )
