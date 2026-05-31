"""The webhook processing job.

Pure logic, kept separate from Soniq registration so it can be awaited
directly in a test with a real session. It receives an id, not an ORM object,
and the session is a parameter rather than something the job opens for itself.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.webhook import WebhookEvent


async def process_payload(event_id: uuid.UUID, db: AsyncSession) -> None:
    event = await db.get(WebhookEvent, event_id)
    if event is None:
        return  # idempotent: a missing record is not an error

    # The demo's "work" is just marking the event handled. A real app would
    # branch on event.slug / event.payload here.
    event.status = "processed"
    await db.commit()
