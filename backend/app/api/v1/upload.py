import math
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ensure_bucket_permission, get_current_user, get_db
from app.api.v1.objects import _check_quota
from app.core.config import settings as app_settings
from app.models.user import User
from app.schemas.upload import (
    MultipartAbortRequest,
    MultipartCompleteRequest,
    MultipartInitRequest,
    MultipartInitResponse,
    PartETag,
    PresignDownloadRequest,
    PresignDownloadResponse,
)
from app.services import s3 as s3_service
from app.services.audit import log_audit, UPLOAD, DOWNLOAD

router = APIRouter(prefix="/buckets", tags=["upload"])


@router.post("/{bucket_name}/upload/init", response_model=MultipartInitResponse)
async def init_multipart_upload(
    bucket_name: str,
    body: MultipartInitRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    ensure_bucket_permission(current_user, bucket_name, "write")
    await _check_quota(db, bucket_name, body.file_size)

    part_size = app_settings.MULTIPART_PART_SIZE_MB * 1024 * 1024
    num_parts = math.ceil(body.file_size / part_size)

    upload_id = await s3_service.create_multipart_upload(
        bucket=bucket_name, key=body.key, content_type=body.content_type
    )
    urls = await s3_service.generate_presigned_upload_urls(
        bucket=bucket_name, key=body.key, upload_id=upload_id, num_parts=num_parts
    )
    return MultipartInitResponse(
        upload_id=upload_id,
        key=body.key,
        part_size=part_size,
        num_parts=num_parts,
        urls=urls,
    )


@router.post("/{bucket_name}/upload/complete", responses={500: {"description": "Failed to complete upload"}})
async def complete_multipart_upload(
    bucket_name: str,
    body: MultipartCompleteRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    ensure_bucket_permission(current_user, bucket_name, "write")
    parts = [
        {"PartNumber": p.part_number, "ETag": p.etag}
        for p in sorted(body.parts, key=lambda x: x.part_number)
    ]
    try:
        await s3_service.complete_multipart_upload(
            bucket=bucket_name, key=body.key, upload_id=body.upload_id, parts=parts
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to complete upload: {e}")

    await log_audit(
        db, current_user, UPLOAD, bucket=bucket_name, object_key=body.key,
        details={"parts": len(body.parts), "method": "multipart"},
        ip_address=request.client.host if request.client else None,
    )
    return {"key": body.key}


@router.post("/{bucket_name}/upload/abort")
async def abort_multipart_upload(
    bucket_name: str,
    body: MultipartAbortRequest,
    current_user: Annotated[User, Depends(get_current_user)],
):
    ensure_bucket_permission(current_user, bucket_name, "write")
    try:
        await s3_service.abort_multipart_upload(
            bucket=bucket_name, key=body.key, upload_id=body.upload_id
        )
    except Exception:
        pass  # best effort
    return {"aborted": True}


@router.post("/{bucket_name}/presign", response_model=PresignDownloadResponse)
async def presign_download(
    bucket_name: str,
    body: PresignDownloadRequest,
    current_user: Annotated[User, Depends(get_current_user)],
):
    ensure_bucket_permission(current_user, bucket_name, "read")
    url = await s3_service.generate_presigned_download_url(
        bucket=bucket_name, key=body.key
    )
    return PresignDownloadResponse(url=url)
