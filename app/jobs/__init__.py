"""Soniq wiring.

`Soniq(...)` does no I/O at construction (the pool is lazy), so importing
this module is safe even when the queue database is down or unconfigured.
The worker process imports this module via `SONIQ_JOBS_MODULES=app.jobs` to
discover the registered job.

Soniq has no database-session injection: a job receives only its arguments
(and an optional `JobContext`). AGENTS.md still requires that the job
*receive* a session rather than open one. We satisfy both with a thin
registered adapter: it owns the per-job session boundary (the job-side
equivalent of the `get_db` request dependency) and delegates to the pure,
session-as-parameter logic in `process_payload`.
"""

import uuid

from soniq import Soniq

from app.database import AsyncSessionLocal
from app.jobs.process_payload import process_payload as _process_payload
from app.jobs.send_verification_email import (
    send_verification_email as _send_verification_email,
)
from app.settings import settings

soniq = Soniq(database_url=settings.soniq_database_url or settings.database_url)


@soniq.job(name="process_payload")  # type: ignore[untyped-decorator]
async def process_payload(event_id: str) -> None:
    """Soniq adapter: open the per-job session, then run the real job."""
    async with AsyncSessionLocal() as db:
        await _process_payload(uuid.UUID(event_id), db)


@soniq.job(  # type: ignore[untyped-decorator]
    name="send_verification_email",
    retries=5,
    retry_delay=1,
    retry_backoff=True,
    retry_max_delay=60,
)
async def send_verification_email(user_id: str, verify_base_url: str) -> None:
    """Soniq adapter for the verification-email send.

    Retries cover the provider's transient failures (5xx, network resets).
    retry_delay + retry_backoff give exponential backoff starting at one
    second, capped at sixty - the right shape for an email provider whose
    bad minutes are usually short. The pure job is idempotent: a retry
    after a partial success at the provider may double-send, which is
    acceptable for a verification email and far better than dropping it.
    """
    async with AsyncSessionLocal() as db:
        await _send_verification_email(uuid.UUID(user_id), verify_base_url, db)


__all__ = ["process_payload", "send_verification_email", "soniq"]
