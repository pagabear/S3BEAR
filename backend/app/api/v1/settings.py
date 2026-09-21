import json
import logging
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.core.config import settings as env_settings
from app.models.settings import AppSetting
from app.models.provider import StorageProvider
from app.models.user import User
from app.schemas.settings import (
    AuthConfig, AuthConfigUpdate, AuthProvider, AuthProviderUpdate,
    AzureAdConfig, AzureAdConfigUpdate, S3ConnectionConfig, S3ConnectionUpdate,
)
from app.services import s3 as s3_service
from app.services.provider_registry import reload_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])

_AUTH_KEYS = ("enable_local_auth", "enable_azure_ad")
_AZURE_KEYS = ("azure_tenant_id", "azure_client_id", "azure_client_secret", "azure_redirect_uri")
_S3_KEYS = ("s3_provider", "s3_access_key_id", "s3_secret_access_key", "s3_region",
            "s3_endpoint_url", "s3_presigned_base", "s3_use_ssl")

# Generic auth providers (real login flow not wired yet — config storage only).
_PROVIDER_DEFS = {
    "github": {"name": "GitHub", "type": "oauth2", "fields": ["client_id", "callback_url"]},
    "saml": {"name": "SAML", "type": "saml", "fields": ["entity_id", "sso_url", "certificate"]},
}


async def load_s3_connection(db: AsyncSession) -> dict | None:
    """Build the runtime S3 config dict from DB, or None if not configured."""
    rows = await _get_rows(db, _S3_KEYS)
    if not rows.get("s3_access_key_id"):
        return None
    return {
        "provider": rows.get("s3_provider", "aws"),
        "access_key": rows.get("s3_access_key_id", ""),
        "secret_key": rows.get("s3_secret_access_key", ""),
        "region": rows.get("s3_region", "us-east-1"),
        "endpoint": rows.get("s3_endpoint_url", ""),
        "presigned_base": rows.get("s3_presigned_base", ""),
        "use_ssl": rows.get("s3_use_ssl", "true") == "true",
    }


async def _get_rows(db: AsyncSession, keys: tuple) -> dict[str, str]:
    result = await db.execute(select(AppSetting).where(AppSetting.key.in_(keys)))
    return {r.key: r.value for r in result.scalars().all()}


async def _upsert(db: AsyncSession, key: str, value: str) -> None:
    result = await db.execute(select(AppSetting).where(AppSetting.key == key))
    row = result.scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))


async def _get_setting(db: AsyncSession, key: str, default: str = "") -> str:
    result = await db.execute(select(AppSetting).where(AppSetting.key == key))
    row = result.scalar_one_or_none()
    return row.value if row else default


# ── Auth toggles ─────────────────────────────────────────────────────────────

@router.get("/auth", response_model=AuthConfig)
async def get_auth_settings(
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    rows = await _get_rows(db, _AUTH_KEYS)
    return AuthConfig(
        enable_local_auth=rows.get("enable_local_auth", "true") == "true",
        enable_azure_ad=rows.get("enable_azure_ad", "true") == "true",
    )


@router.put("/auth", response_model=AuthConfig)
async def update_auth_settings(
    body: AuthConfigUpdate,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _upsert(db, "enable_local_auth", str(body.enable_local_auth).lower())
    await _upsert(db, "enable_azure_ad", str(body.enable_azure_ad).lower())
    await db.flush()
    rows = await _get_rows(db, _AUTH_KEYS)
    return AuthConfig(
        enable_local_auth=rows.get("enable_local_auth", "true") == "true",
        enable_azure_ad=rows.get("enable_azure_ad", "true") == "true",
    )


# ── Azure AD config ───────────────────────────────────────────────────────────

@router.get("/azure", response_model=AzureAdConfig)
async def get_azure_settings(
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    rows = await _get_rows(db, _AZURE_KEYS)
    return AzureAdConfig(
        tenant_id=rows.get("azure_tenant_id") or env_settings.AZURE_TENANT_ID,
        client_id=rows.get("azure_client_id") or env_settings.AZURE_CLIENT_ID,
        redirect_uri=rows.get("azure_redirect_uri") or env_settings.AZURE_REDIRECT_URI,
        has_secret=bool(rows.get("azure_client_secret") or env_settings.AZURE_CLIENT_SECRET),
    )


@router.put("/azure", response_model=AzureAdConfig)
async def update_azure_settings(
    body: AzureAdConfigUpdate,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _upsert(db, "azure_tenant_id", body.tenant_id)
    await _upsert(db, "azure_client_id", body.client_id)
    await _upsert(db, "azure_redirect_uri", body.redirect_uri)
    if body.client_secret is not None:
        await _upsert(db, "azure_client_secret", body.client_secret)
    await db.flush()

    rows = await _get_rows(db, _AZURE_KEYS)
    return AzureAdConfig(
        tenant_id=rows.get("azure_tenant_id") or env_settings.AZURE_TENANT_ID,
        client_id=rows.get("azure_client_id") or env_settings.AZURE_CLIENT_ID,
        redirect_uri=rows.get("azure_redirect_uri") or env_settings.AZURE_REDIRECT_URI,
        has_secret=bool(rows.get("azure_client_secret") or env_settings.AZURE_CLIENT_SECRET),
    )


# ── Storage stats & quotas ───────────────────────────────────────────────────

@router.get("/storage")
async def get_storage_stats(
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    stats = await s3_service.get_storage_stats()

    # Load global quota
    global_quota_gb = await _get_setting(db, "storage_quota_gb", "0")
    stats["quota_bytes"] = int(float(global_quota_gb) * 1024 * 1024 * 1024) if float(global_quota_gb) > 0 else 0

    # Load per-bucket quotas
    result = await db.execute(
        select(AppSetting).where(AppSetting.key.like("bucket_quota_gb:%"))
    )
    bucket_quotas = {r.key.split(":", 1)[1]: float(r.value) for r in result.scalars().all()}

    for b in stats["buckets"]:
        quota_gb = bucket_quotas.get(b["name"], 0)
        b["quota_bytes"] = int(quota_gb * 1024 * 1024 * 1024) if quota_gb > 0 else 0

    return stats


class GlobalQuotaUpdate(BaseModel):
    quota_gb: float


@router.put("/storage/quota")
async def update_global_quota(
    body: GlobalQuotaUpdate,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _upsert(db, "storage_quota_gb", str(body.quota_gb))
    await db.flush()
    return {"quota_gb": body.quota_gb}


class BucketQuotaUpdate(BaseModel):
    quota_gb: float


@router.put("/storage/quota/{bucket_name}")
async def update_bucket_quota(
    bucket_name: str,
    body: BucketQuotaUpdate,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    key = f"bucket_quota_gb:{bucket_name}"
    if body.quota_gb <= 0:
        # Remove quota
        result = await db.execute(select(AppSetting).where(AppSetting.key == key))
        row = result.scalar_one_or_none()
        if row:
            await db.delete(row)
    else:
        await _upsert(db, key, str(body.quota_gb))
    await db.flush()
    return {"bucket": bucket_name, "quota_gb": body.quota_gb}


# ── S3 connection ─────────────────────────────────────────────────────────────

# The legacy single-connection endpoints below are kept for backward
# compatibility and now operate on the *default* storage provider. New multi-
# provider management lives under /api/v1/providers.

async def _get_default_provider(db: AsyncSession) -> StorageProvider | None:
    return (await db.execute(
        select(StorageProvider).where(StorageProvider.is_default.is_(True))
    )).scalar_one_or_none()


async def _build_connection_response(db: AsyncSession) -> S3ConnectionConfig:
    provider = await _get_default_provider(db)
    if provider is not None:
        return S3ConnectionConfig(
            provider=provider.provider_type,
            access_key_id=provider.access_key_id,
            region=provider.region,
            endpoint_url=provider.endpoint_url,
            presigned_base=provider.presigned_base,
            use_ssl=provider.use_ssl,
            has_secret=bool(provider.secret_access_key),
            configured=True,
            source="db",
        )
    # Fall back to env config (read-only view)
    return S3ConnectionConfig(
        provider="minio" if env_settings.AWS_ENDPOINT_URL else "aws",
        access_key_id=env_settings.AWS_ACCESS_KEY_ID,
        region=env_settings.AWS_REGION,
        endpoint_url=env_settings.AWS_ENDPOINT_URL,
        presigned_base=env_settings.PRESIGNED_URL_BASE,
        use_ssl=True,
        has_secret=bool(env_settings.AWS_SECRET_ACCESS_KEY),
        configured=False,
        source="env",
    )


@router.get("/storage/connection", response_model=S3ConnectionConfig)
async def get_s3_connection(
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await _build_connection_response(db)


@router.put("/storage/connection", response_model=S3ConnectionConfig)
async def update_s3_connection(
    body: S3ConnectionUpdate,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    provider = await _get_default_provider(db)
    secret = body.secret_access_key if body.secret_access_key else (provider.secret_access_key if provider else "")
    if not secret:
        raise HTTPException(status_code=400, detail="Secret access key is required")

    cfg = {
        "access_key": body.access_key_id,
        "secret_key": secret,
        "region": body.region,
        "endpoint": body.endpoint_url,
        "presigned_base": body.presigned_base,
    }
    # Validate before persisting so a bad credential never replaces a working one.
    try:
        await s3_service.test_config(cfg)
    except Exception:  # noqa: BLE001
        logger.warning("S3 connection test failed during update", exc_info=True)
        raise HTTPException(status_code=400, detail="Connection test failed. Check server logs for details.")

    if provider is None:
        provider = StorageProvider(name="Default", is_default=True)
        db.add(provider)
    provider.provider_type = body.provider
    provider.access_key_id = body.access_key_id
    provider.secret_access_key = secret
    provider.region = body.region
    provider.endpoint_url = body.endpoint_url
    provider.presigned_base = body.presigned_base
    provider.use_ssl = body.use_ssl
    await db.flush()
    await db.commit()
    await reload_registry(db)
    return await _build_connection_response(db)


@router.post("/storage/connection/test")
async def test_s3_connection(
    body: S3ConnectionUpdate,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    provider = await _get_default_provider(db)
    secret = body.secret_access_key if body.secret_access_key else (provider.secret_access_key if provider else "")
    if not secret:
        raise HTTPException(status_code=400, detail="Secret access key is required")
    cfg = {
        "access_key": body.access_key_id, "secret_key": secret, "region": body.region,
        "endpoint": body.endpoint_url, "presigned_base": body.presigned_base,
    }
    try:
        await s3_service.test_config(cfg)
    except Exception:  # noqa: BLE001
        logger.warning("S3 connection test failed", exc_info=True)
        return {"ok": False, "error": "Connection test failed. Check server logs for details."}
    return {"ok": True, "error": None}


# ── Generic auth providers ────────────────────────────────────────────────────

def _provider_state(raw: str | None) -> dict:
    if not raw:
        return {"enabled": False, "config": {}, "secret": ""}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {"enabled": False, "config": {}, "secret": ""}
    return {
        "enabled": bool(data.get("enabled")),
        "config": data.get("config") or {},
        "secret": data.get("secret") or "",
    }


@router.get("/auth/providers", response_model=list[AuthProvider])
async def list_auth_providers(
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    keys = tuple(f"authprovider:{pid}" for pid in _PROVIDER_DEFS)
    rows = await _get_rows(db, keys)
    result = []
    for pid, defn in _PROVIDER_DEFS.items():
        state = _provider_state(rows.get(f"authprovider:{pid}"))
        result.append(AuthProvider(
            id=pid, name=defn["name"], type=defn["type"],
            enabled=state["enabled"],
            configured=bool(state["config"]),
            has_secret=bool(state["secret"]),
            config=state["config"],
        ))
    return result


@router.put("/auth/providers/{provider_id}", response_model=AuthProvider)
async def update_auth_provider(
    provider_id: str,
    body: AuthProviderUpdate,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    defn = _PROVIDER_DEFS.get(provider_id)
    if defn is None:
        raise HTTPException(status_code=404, detail="Unknown provider")
    key = f"authprovider:{provider_id}"
    current = _provider_state(await _get_setting(db, key))
    secret = body.secret if body.secret else current["secret"]
    await _upsert(db, key, json.dumps({
        "enabled": body.enabled,
        "config": body.config,
        "secret": secret,
    }))
    await db.flush()
    return AuthProvider(
        id=provider_id, name=defn["name"], type=defn["type"],
        enabled=body.enabled, configured=bool(body.config), has_secret=bool(secret),
        config=body.config,
    )
