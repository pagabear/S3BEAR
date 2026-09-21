from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.deps import ensure_bucket_permission, get_current_user
from app.api.v1.image_utils import parse_or_400, render_transformed
from app.models.user import User
from app.services import s3 as s3_service

router = APIRouter(prefix="/images", tags=["images"])

ALLOWED_CONTENT_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "image/svg+xml", "image/bmp", "image/tiff", "image/avif",
}


def _check_read(user: User, bucket_name: str) -> None:
    ensure_bucket_permission(user, bucket_name, "read")


@router.get("/{bucket_name}/{object_key:path}", responses={403: {"description": "No read permission"}, 404: {"description": "Object not found"}, 415: {"description": "Not an image"}})
async def proxy_image(
    bucket_name: str,
    object_key: str,
    current_user: Annotated[User, Depends(get_current_user)],
    w: int | None = Query(None, ge=1, description="Resize width (px)"),
    h: int | None = Query(None, ge=1, description="Resize height (px)"),
    fmt: str | None = Query(None, alias="format", description="webp | jpeg | png"),
    q: int | None = Query(None, ge=1, le=100, description="Quality 1-100 (webp/jpeg)"),
    fit: str | None = Query(None, description="contain (default) | cover"),
):
    _check_read(current_user, bucket_name)

    spec = parse_or_400(w, h, fmt, q, fit)
    if spec is not None:
        return await render_transformed(bucket_name, object_key, spec)

    try:
        generator, content_type, content_length = await s3_service.stream_object(
            bucket=bucket_name, key=object_key
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Object not found")

    if content_type not in ALLOWED_CONTENT_TYPES:
        # Try to infer from key extension
        import mimetypes
        guessed, _ = mimetypes.guess_type(object_key)
        if not guessed or guessed not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(status_code=415, detail="Not an image")
        content_type = guessed

    headers = {
        "Cache-Control": "public, max-age=3600",
        "Content-Length": str(content_length),
    }
    return StreamingResponse(generator, media_type=content_type, headers=headers)
