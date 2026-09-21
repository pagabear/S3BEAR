"""Webhook service.

Admins register endpoints subscribed to a set of events (the same names as audit
actions). When an audited, state-changing action occurs, a pending delivery row is
enqueued for each matching enabled endpoint. A scheduler job then POSTs the payload
with an HMAC-SHA256 signature, retrying with backoff up to WEBHOOK_MAX_ATTEMPTS.

Pure helpers depend only on the standard library and app config; DB helpers import
models lazily.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from app.core.config import settings

if TYPE_CHECKING:
    import uuid
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.models.webhook import WebhookEndpoint

SIGNATURE_HEADER = "X-S3Bear-Signature"
EVENT_HEADER = "X-S3Bear-Event"
DELIVERY_HEADER = "X-S3Bear-Delivery"

# Backoff schedule (seconds) indexed by attempt number just made: attempt 1 -> wait 60s,
# attempt 2 -> 300s, attempt 3 -> 1800s. Length ties to WEBHOOK_MAX_ATTEMPTS.
_BACKOFF_SECONDS = [60, 300, 1800]

STATUS_PENDING = "pending"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"


# --- pure helpers -----------------------------------------------------------

def generate_secret() -> str:
    return secrets.token_urlsafe(32)


def sign_payload(secret: str, body: bytes) -> str:
    """HMAC-SHA256 signature of the raw request body, as sent in the signature header."""
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def event_matches(subscribed_events: list[str], action: str) -> bool:
    return "*" in subscribed_events or action in subscribed_events


def next_retry_at(attempts_made: int, now: datetime | None = None) -> datetime | None:
    """When to next retry after `attempts_made` failed attempts, or None when the
    max-attempts budget is exhausted."""
    if attempts_made >= settings.WEBHOOK_MAX_ATTEMPTS:
        return None
    now = now or datetime.now(timezone.utc)
    idx = min(attempts_made - 1, len(_BACKOFF_SECONDS) - 1)
    return now + timedelta(seconds=_BACKOFF_SECONDS[idx])


def build_payload(
    event: str,
    user_id: str | None,
    user_email: str,
    bucket: str | None,
    object_key: str | None,
    details: dict | None,
) -> dict:
    return {
        "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actor": {"user_id": user_id, "email": user_email},
        "bucket": bucket,
        "object_key": object_key,
        "details": details,
    }


# --- DB-touching helpers ----------------------------------------------------

async def enqueue_event(
    db: "AsyncSession",
    action: str,
    payload: dict,
) -> int:
    """Create pending delivery rows for every enabled endpoint subscribed to `action`.
    Best-effort: returns the number of deliveries enqueued. Runs in the caller's
    transaction so a rolled-back request produces no deliveries."""
    if not settings.WEBHOOKS_ENABLED:
        return 0

    from sqlalchemy import select
    from app.models.webhook import WebhookEndpoint, WebhookDelivery

    result = await db.execute(
        select(WebhookEndpoint).where(WebhookEndpoint.enabled.is_(True))
    )
    endpoints = result.scalars().all()

    count = 0
    for ep in endpoints:
        if not event_matches(ep.events or [], action):
            continue
        db.add(WebhookDelivery(
            endpoint_id=ep.id,
            event=action,
            payload=payload,
            status=STATUS_PENDING,
            attempts=0,
        ))
        count += 1
    if count:
        await db.flush()
    return count


async def deliver_one(client, endpoint: "WebhookEndpoint", delivery) -> None:
    """Attempt a single delivery, updating its status/attempts in place. `client`
    is an httpx.AsyncClient. Never raises — records the outcome on the row."""
    import json as _json

    body = _json.dumps(delivery.payload, default=str).encode()
    headers = {
        "Content-Type": "application/json",
        EVENT_HEADER: delivery.event,
        DELIVERY_HEADER: str(delivery.id),
        SIGNATURE_HEADER: sign_payload(endpoint.secret, body),
    }
    delivery.attempts += 1
    now = datetime.now(timezone.utc)
    try:
        resp = await client.post(
            endpoint.url, content=body, headers=headers,
            timeout=settings.WEBHOOK_TIMEOUT_SECONDS,
        )
        delivery.last_status_code = resp.status_code
        if 200 <= resp.status_code < 300:
            delivery.status = STATUS_SUCCESS
            delivery.delivered_at = now
            delivery.next_retry_at = None
            delivery.last_error = None
            return
        delivery.last_error = f"HTTP {resp.status_code}"
    except Exception as e:  # noqa: BLE001
        delivery.last_status_code = None
        delivery.last_error = str(e)[:500]

    retry = next_retry_at(delivery.attempts, now)
    delivery.next_retry_at = retry
    delivery.status = STATUS_PENDING if retry is not None else STATUS_FAILED


async def dispatch_pending(db: "AsyncSession") -> dict:
    """Deliver all pending deliveries whose retry time is due. Returns a summary."""
    import httpx
    from sqlalchemy import select
    from app.models.webhook import WebhookEndpoint, WebhookDelivery

    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(WebhookDelivery).where(
            WebhookDelivery.status == STATUS_PENDING,
            (WebhookDelivery.next_retry_at.is_(None)) | (WebhookDelivery.next_retry_at <= now),
        ).limit(100)
    )
    deliveries = list(result.scalars().all())
    if not deliveries:
        return {"attempted": 0, "success": 0, "failed": 0}

    # Preload endpoints referenced by these deliveries.
    endpoint_ids = {d.endpoint_id for d in deliveries}
    ep_result = await db.execute(
        select(WebhookEndpoint).where(WebhookEndpoint.id.in_(endpoint_ids))
    )
    endpoints = {ep.id: ep for ep in ep_result.scalars().all()}

    success = 0
    async with httpx.AsyncClient() as client:
        for d in deliveries:
            ep = endpoints.get(d.endpoint_id)
            if ep is None:  # endpoint deleted; drop the delivery
                d.status = STATUS_FAILED
                d.last_error = "endpoint removed"
                d.next_retry_at = None
                continue
            await deliver_one(client, ep, d)
            if d.status == STATUS_SUCCESS:
                success += 1
    await db.flush()
    return {
        "attempted": len(deliveries),
        "success": success,
        "failed": len(deliveries) - success,
    }
