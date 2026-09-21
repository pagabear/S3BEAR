import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings

logger = logging.getLogger(__name__)

_scheduler: Optional[BackgroundScheduler] = None


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        jobstores = {
            "default": SQLAlchemyJobStore(url=settings.DATABASE_URL_SYNC)
        }
        _scheduler = BackgroundScheduler(jobstores=jobstores)
    return _scheduler


def _run_policy_sync(policy_id: str, bucket_patterns: list, prefix_filter, older_than_days,
                     target_type: str = "pattern", tag_key=None, tag_value=None):
    """Sync wrapper for async cleanup, called by APScheduler."""
    from app.services.cleanup import run_policy
    from app.core.database import AsyncSessionLocal
    from app.models.policy import CleanupPolicy
    import sqlalchemy as sa

    async def _inner():
        result = await run_policy(
            policy_id=policy_id,
            prefix_filter=prefix_filter,
            older_than_days=older_than_days,
            target_type=target_type,
            bucket_patterns=bucket_patterns,
            tag_key=tag_key,
            tag_value=tag_value,
        )
        async with AsyncSessionLocal() as db:
            res = await db.execute(
                sa.select(CleanupPolicy).where(CleanupPolicy.id == policy_id)
            )
            policy = res.scalar_one_or_none()
            if policy:
                policy.last_run_at = datetime.now(timezone.utc)
                policy.last_run_status = result["status"]
                policy.last_run_deleted_count = result["deleted_count"]

            # Write audit log for the cleanup run
            from app.services.audit import log_audit, CLEANUP
            await log_audit(
                db, user=None, action=CLEANUP,
                details={
                    "policy_id": policy_id,
                    "policy_name": policy.name if policy else "unknown",
                    "target_type": target_type,
                    "bucket_patterns": bucket_patterns,
                    "tag_key": tag_key,
                    "tag_value": tag_value,
                    "prefix_filter": prefix_filter,
                    "older_than_days": older_than_days,
                    "deleted_count": result["deleted_count"],
                    "status": result["status"],
                    "errors": result.get("errors", []),
                },
            )
            await db.commit()
        return result

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(_inner())
        logger.info(f"Policy {policy_id} run complete: {result['deleted_count']} deleted, status={result['status']}")
    except Exception as e:
        logger.exception(f"Policy {policy_id} run failed: {e}")
    finally:
        loop.close()


def reschedule_policy(policy) -> None:
    scheduler = get_scheduler()
    job_id = f"policy_{policy.id}"

    if not policy.is_active:
        remove_policy_job(str(policy.id))
        return

    try:
        trigger = CronTrigger.from_crontab(policy.cron_expression)
    except Exception as e:
        logger.error(f"Invalid cron expression for policy {policy.id}: {e}")
        return

    kwargs = {
        "policy_id": str(policy.id),
        "bucket_patterns": policy.bucket_patterns,
        "prefix_filter": policy.prefix_filter,
        "older_than_days": policy.older_than_days,
        "target_type": policy.target_type,
        "tag_key": policy.tag_key,
        "tag_value": policy.tag_value,
    }

    if scheduler.get_job(job_id):
        scheduler.reschedule_job(job_id, trigger=trigger)
        scheduler.modify_job(job_id, kwargs=kwargs)
    else:
        scheduler.add_job(
            _run_policy_sync,
            trigger=trigger,
            id=job_id,
            kwargs=kwargs,
            replace_existing=True,
            misfire_grace_time=3600,
        )
    logger.info(f"Scheduled policy job: {job_id} with cron={policy.cron_expression}")


def remove_policy_job(policy_id: str) -> None:
    scheduler = get_scheduler()
    job_id = f"policy_{policy_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)


async def load_all_policies() -> None:
    """Load all active policies from DB and schedule them on startup."""
    from app.core.database import AsyncSessionLocal
    from app.models.policy import CleanupPolicy
    import sqlalchemy as sa

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            sa.select(CleanupPolicy).where(CleanupPolicy.is_active.is_(True))
        )
        policies = result.scalars().all()

    scheduler = get_scheduler()
    for policy in policies:
        reschedule_policy(policy)

    logger.info(f"Loaded {len(policies)} cleanup policies into scheduler")


def _run_audit_log_cleanup_sync():
    """Sync wrapper for async audit log cleanup, called daily by APScheduler."""
    from app.services.audit import cleanup_old_audit_logs

    async def _inner():
        return await cleanup_old_audit_logs()

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(_inner())
        logger.info("Audit log cleanup complete: %s", result)
    except Exception as e:
        logger.exception("Audit log cleanup failed: %s", e)
    finally:
        loop.close()


def _run_webhook_dispatch_sync():
    """Sync wrapper for the async webhook dispatcher, called on an interval.

    APScheduler runs this in a background thread with a fresh event loop each
    time. The global async engine's asyncpg pool is bound to the main uvicorn
    loop, so reusing it here raises "attached to a different loop". We therefore
    create (and dispose) a dedicated engine bound to this loop."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.services.webhook import dispatch_pending
    from app.core.config import settings

    async def _inner():
        engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
        Session = async_sessionmaker(bind=engine, expire_on_commit=False)
        try:
            async with Session() as db:
                result = await dispatch_pending(db)
                await db.commit()
                return result
        finally:
            await engine.dispose()

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(_inner())
        if result.get("attempted"):
            logger.info("Webhook dispatch: %s", result)
    except Exception as e:
        logger.exception("Webhook dispatch failed: %s", e)
    finally:
        loop.close()


def _schedule_webhook_dispatch() -> None:
    """Schedule the webhook dispatcher to run every 20 seconds."""
    if not settings.WEBHOOKS_ENABLED:
        return

    scheduler = get_scheduler()
    job_id = "webhook_dispatch"
    if not scheduler.get_job(job_id):
        from apscheduler.triggers.interval import IntervalTrigger
        scheduler.add_job(
            _run_webhook_dispatch_sync,
            trigger=IntervalTrigger(seconds=20),
            id=job_id,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
        )
        logger.info("Scheduled webhook dispatch job (every 20s)")


def _schedule_audit_log_cleanup() -> None:
    """Schedule daily audit log cleanup at 02:00 UTC."""
    if not settings.AUDIT_LOG_ENABLED:
        return

    scheduler = get_scheduler()
    job_id = "audit_log_cleanup"

    if not scheduler.get_job(job_id):
        scheduler.add_job(
            _run_audit_log_cleanup_sync,
            trigger=CronTrigger(hour=2, minute=0),
            id=job_id,
            replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info("Scheduled audit log cleanup job (daily at 02:00 UTC, retention=%d days)", settings.AUDIT_LOG_RETENTION_DAYS)


def start_scheduler() -> None:
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        _schedule_audit_log_cleanup()
        _schedule_webhook_dispatch()
        logger.info("APScheduler started")


def stop_scheduler() -> None:
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")
