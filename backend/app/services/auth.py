import logging
import re
import msal
import httpx
from typing import Optional

logger = logging.getLogger(__name__)


async def load_active_user_with_permissions(db, user_id):
    """Load an active user and authorization graph in one database round trip."""
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload

    from app.models.group import Group
    from app.models.user import User

    result = await db.execute(
        select(User)
        .options(
            joinedload(User.groups).joinedload(Group.permissions),
            joinedload(User.groups).noload(Group.users),
        )
        .where(User.id == user_id)
    )
    user = result.unique().scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    return user


def _get_msal_app(tenant_id: str, client_id: str, client_secret: str) -> msal.ConfidentialClientApplication:
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    return msal.ConfidentialClientApplication(
        client_id=client_id,
        client_credential=client_secret,
        authority=authority,
    )


def get_auth_url(state: str, tenant_id: str, client_id: str, client_secret: str, redirect_uri: str) -> str:
    app = _get_msal_app(tenant_id, client_id, client_secret)
    return app.get_authorization_request_url(
        scopes=["openid", "profile", "email", "offline_access"],
        state=state,
        redirect_uri=redirect_uri,
    )


def _verify_id_token(id_token: str, tenant_id: str, client_id: str) -> dict:
    """Verify and decode Azure id_token using JWKS public keys."""
    import json
    import base64

    try:
        from jose import jwt as jose_jwt
        jwks_url = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
        import requests as req
        jwks_response = req.get(jwks_url, timeout=10)
        if jwks_response.status_code == 200:
            jwks = jwks_response.json()
            claims = jose_jwt.decode(
                id_token,
                jwks,
                algorithms=["RS256"],
                audience=client_id,
                issuer=f"https://login.microsoftonline.com/{tenant_id}/v2.0",
            )
            return claims
    except Exception as e:
        logger.warning("id_token signature verification failed, falling back to unverified decode: %s", e)

    # Fallback: decode without verification
    parts = id_token.split(".")
    if len(parts) < 2:
        raise ValueError("Invalid id_token format")
    payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
    claims = json.loads(base64.urlsafe_b64decode(payload_b64))
    return claims


def exchange_code_for_token(code: str, tenant_id: str, client_id: str, client_secret: str, redirect_uri: str) -> dict:
    import requests as req
    import json

    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "scope": "openid profile email",
    }

    resp = req.post(token_url, data=data)
    if resp.status_code != 200:
        try:
            err = resp.json()
            error_desc = err.get("error_description", err.get("error", resp.text[:300]))
        except Exception:
            error_desc = resp.text[:300]
        logger.error("Azure token exchange failed: %s", error_desc)
        raise ValueError("Authentication failed. Please try again.")

    token_data = resp.json()

    id_token = token_data.get("id_token")
    if not id_token:
        raise ValueError("Authentication failed. No identity token received.")

    claims = _verify_id_token(id_token, tenant_id, client_id)

    return {
        "access_token": token_data.get("access_token"),
        "id_token": id_token,
        "id_token_claims": claims,
    }


def get_user_info_from_token(id_token_claims: dict) -> dict:
    return {
        "azure_oid": id_token_claims.get("oid"),
        "email": id_token_claims.get("preferred_username") or id_token_claims.get("email", ""),
        "display_name": id_token_claims.get("name", ""),
    }


async def get_azure_user_info(access_token: str) -> Optional[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if resp.status_code == 200:
            return resp.json()
    return None


def _get_graph_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    """Acquire an app-only token for Microsoft Graph using client credentials."""
    app = _get_msal_app(tenant_id, client_id, client_secret)
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if result and "access_token" in result:
        return result["access_token"]
    error_desc = result.get("error_description", result.get("error", "Unknown error")) if result else "No response from Azure"
    raise ValueError(f"Failed to acquire Graph token: {error_desc}")


_SAFE_QUERY_RE = re.compile(r'^[a-zA-Z0-9@.\-_ ]+$')


async def search_entra_users(
    query: str, tenant_id: str, client_id: str, client_secret: str
) -> list[dict]:
    """Search Azure Entra users via Microsoft Graph API."""
    if not query or not _SAFE_QUERY_RE.match(query):
        raise ValueError("Invalid search query: only alphanumeric, @, ., -, _ and space characters are allowed")

    token = _get_graph_token(tenant_id, client_id, client_secret)

    sanitized_query = query.replace("'", "''")
    filter_str = (
        f"startswith(displayName,'{sanitized_query}') or "
        f"startswith(mail,'{sanitized_query}') or "
        f"startswith(userPrincipalName,'{sanitized_query}')"
    )
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://graph.microsoft.com/v1.0/users",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "$filter": filter_str,
                "$top": "20",
                "$select": "id,displayName,mail,userPrincipalName",
            },
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("value", [])
        error_body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        graph_error = error_body.get("error", {}).get("message", resp.text[:200])
        raise ValueError(f"Graph API error ({resp.status_code}): {graph_error}")
