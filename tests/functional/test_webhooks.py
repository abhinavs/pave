"""Phase 4: webhook ingestion + the Soniq processing job.

The endpoint accepts an arbitrary JSON payload at `/webhooks/{slug}`, records
it, and hands the id (not the ORM object) to a Soniq job. Soniq's `enqueue`
is faked here: this suite proves the HTTP contract and the enqueue call, not
the queue itself. The job's own logic is exercised directly against a session.
"""

import uuid
from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.process_payload import process_payload
from app.models.webhook import WebhookEvent


class _EnqueueRecorder:
    """Stands in for `soniq.enqueue`: records the call, returns a job id."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, dict[str, object]]] = []

    async def __call__(self, target: object, **kwargs: object) -> str:
        self.calls.append((target, kwargs))
        return "fake-job-id"


@pytest_asyncio.fixture
async def fake_enqueue(
    monkeypatch: object,
) -> AsyncGenerator[_EnqueueRecorder, None]:
    import app.jobs

    recorder = _EnqueueRecorder()
    monkeypatch.setattr(app.jobs.soniq, "enqueue", recorder)  # type: ignore[attr-defined]
    yield recorder


async def test_post_webhook_returns_202(
    async_client: AsyncClient, fake_enqueue: _EnqueueRecorder
) -> None:
    resp = await async_client.post(
        "/webhooks/stripe", json={"type": "charge.succeeded", "amount": 4200}
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body["slug"] == "stripe"
    assert body["status"] == "pending"
    assert "password_hash" not in body and "payload" not in body


async def test_post_webhook_stores_event_with_payload(
    async_client: AsyncClient,
    db_session: AsyncSession,
    fake_enqueue: _EnqueueRecorder,
) -> None:
    payload = {"type": "issue.opened", "number": 7}
    await async_client.post("/webhooks/github", json=payload)

    event = (
        await db_session.execute(
            select(WebhookEvent).where(WebhookEvent.slug == "github")
        )
    ).scalar_one()
    assert event.payload == payload
    assert event.status == "pending"


async def test_post_webhook_enqueues_job_with_event_id(
    async_client: AsyncClient,
    db_session: AsyncSession,
    fake_enqueue: _EnqueueRecorder,
) -> None:
    await async_client.post("/webhooks/linear", json={"ok": True})

    event = (
        await db_session.execute(
            select(WebhookEvent).where(WebhookEvent.slug == "linear")
        )
    ).scalar_one()

    assert len(fake_enqueue.calls) == 1
    _target, kwargs = fake_enqueue.calls[0]
    # AGENTS.md: enqueue receives a primitive id, never the ORM object.
    assert kwargs == {"event_id": str(event.id)}


async def test_process_payload_idempotent_on_missing_record(
    db_session: AsyncSession,
) -> None:
    # A job for a record that no longer exists is a no-op, not an error.
    await process_payload(uuid.uuid4(), db_session)


async def test_process_payload_marks_event_processed(
    db_session: AsyncSession,
) -> None:
    event = WebhookEvent(slug="demo", payload={"hi": 1})
    db_session.add(event)
    await db_session.commit()

    await process_payload(event.id, db_session)
    await db_session.refresh(event)

    assert event.status == "processed"
