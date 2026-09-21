import os
from typing import Annotated
from fastapi import APIRouter, Depends, File, HTTPException, Path, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ensure_bucket_permission, get_current_user, get_db
from app.models.settings import AppSetting
from app.models.user import User
from app.schemas.s3 import BulkCopyMoveRequest, BulkResult, CopyMoveRequest, DeleteRequest, DeleteResult
from app.services import s3 as s3_service
from app.services.audit import log_audit, UPLOAD, DELETE, COPY, MOVE

router = APIRouter(prefix="/buckets", tags=["objects"])


async def _check_quota(db: AsyncSession, bucket_name: str, upload_size: int) -> None:
    """Check both global and bucket quotas before upload."""
    # Check global quota
    result = await db.execute(select(AppSetting).where(AppSetting.key == "storage_quota_gb"))
    row = result.scalar_one_or_none()
    if row and float(row.value) > 0:
        quota_bytes = int(float(row.value) * 1024 * 1024 * 1024)
        stats = await s3_service.get_storage_stats()
        if stats["total_size"] + upload_size > quota_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Global storage quota exceeded ({row.value} GB limit)",
            )

    # Check bucket quota
    result = await db.execute(
        select(AppSetting).where(AppSetting.key == f"bucket_quota_gb:{bucket_name}")
    )
    row = result.scalar_one_or_none()
    if row and float(row.value) > 0:
        quota_bytes = int(float(row.value) * 1024 * 1024 * 1024)
        bucket_stats = await s3_service.get_bucket_size(bucket_name)
        if bucket_stats["size"] + upload_size > quota_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Bucket '{bucket_name}' quota exceeded ({row.value} GB limit)",
            )


@router.post("/{bucket_name}/objects", status_code=201)
async def upload_object(
    bucket_name: str,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: Annotated[UploadFile, File()],
    prefix: str = "",
):
    ensure_bucket_permission(current_user, bucket_name, "write")
    key = f"{prefix}{file.filename}" if prefix else file.filename

    # Measure the upload without reading it into memory. Starlette spools the
    # body to a temp file, so seeking to the end gives the size cheaply and the
    # quota check runs before we transfer a single byte to S3.
    size = file.file.seek(0, os.SEEK_END)
    file.file.seek(0)
    await _check_quota(db, bucket_name, size)

    content_type = file.content_type or "application/octet-stream"
    # Stream straight from the spooled file to S3 instead of buffering the whole
    # object as a bytes value in the request handler.
    await s3_service.upload_fileobj(
        bucket=bucket_name, key=key, fileobj=file.file, content_type=content_type
    )
    await log_audit(db, current_user, UPLOAD, bucket=bucket_name, object_key=key,
                    details={"size": size, "content_type": content_type},
                    ip_address=request.client.host if request.client else None)
    return {"key": key, "size": size}


@router.delete("/{bucket_name}/objects", response_model=DeleteResult)
async def delete_objects(
    bucket_name: str,
    body: DeleteRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    ensure_bucket_permission(current_user, bucket_name, "delete")
    result = await s3_service.delete_objects(bucket=bucket_name, keys=body.keys)
    for key in body.keys:
        await log_audit(db, current_user, DELETE, bucket=bucket_name, object_key=key,
                        ip_address=request.client.host if request.client else None)
    return DeleteResult(**result)


@router.post("/{bucket_name}/objects/copy", responses={403: {"description": "Insufficient permissions"}, 404: {"description": "Source object not found"}})
async def copy_object(
    bucket_name: str,
    body: CopyMoveRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    ensure_bucket_permission(current_user, body.source_bucket, "read")
    ensure_bucket_permission(current_user, bucket_name, "write")
    try:
        await s3_service.copy_object(body.source_bucket, body.source_key, bucket_name, body.dest_key)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await log_audit(db, current_user, COPY, bucket=bucket_name, object_key=body.dest_key,
                    details={"source_bucket": body.source_bucket, "source_key": body.source_key},
                    ip_address=request.client.host if request.client else None)
    return {"key": body.dest_key}


@router.post("/{bucket_name}/objects/move", responses={403: {"description": "Insufficient permissions"}, 404: {"description": "Source object not found"}})
async def move_object(
    bucket_name: str,
    body: CopyMoveRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    ensure_bucket_permission(current_user, body.source_bucket, "read")
    ensure_bucket_permission(current_user, body.source_bucket, "delete")
    ensure_bucket_permission(current_user, bucket_name, "write")
    try:
        await s3_service.move_object(body.source_bucket, body.source_key, bucket_name, body.dest_key)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await log_audit(db, current_user, MOVE, bucket=bucket_name, object_key=body.dest_key,
                    details={"source_bucket": body.source_bucket, "source_key": body.source_key},
                    ip_address=request.client.host if request.client else None)
    return {"key": body.dest_key}


@router.post("/{bucket_name}/objects/bulk-copy", response_model=BulkResult,
             responses={403: {"description": "Insufficient permissions"}})
async def bulk_copy_objects(
    bucket_name: str,
    body: BulkCopyMoveRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    ensure_bucket_permission(current_user, body.source_bucket, "read")
    ensure_bucket_permission(current_user, bucket_name, "write")
    result = await s3_service.bulk_copy_move(
        body.source_bucket, body.keys, bucket_name, body.dest_prefix, move=False
    )
    await log_audit(db, current_user, COPY, bucket=bucket_name,
                    details={"bulk": True, "source_bucket": body.source_bucket,
                             "count": len(result["succeeded"]), "errors": len(result["errors"])},
                    ip_address=request.client.host if request.client else None)
    return BulkResult(**result)


@router.post("/{bucket_name}/objects/bulk-move", response_model=BulkResult,
             responses={403: {"description": "Insufficient permissions"}})
async def bulk_move_objects(
    bucket_name: str,
    body: BulkCopyMoveRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    ensure_bucket_permission(current_user, body.source_bucket, "read")
    ensure_bucket_permission(current_user, body.source_bucket, "delete")
    ensure_bucket_permission(current_user, bucket_name, "write")
    result = await s3_service.bulk_copy_move(
        body.source_bucket, body.keys, bucket_name, body.dest_prefix, move=True
    )
    await log_audit(db, current_user, MOVE, bucket=bucket_name,
                    details={"bulk": True, "source_bucket": body.source_bucket,
                             "count": len(result["succeeded"]), "errors": len(result["errors"])},
                    ip_address=request.client.host if request.client else None)
    return BulkResult(**result)
