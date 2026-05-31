"""The webhook demo: a table plus HTMX live search.

Two surfaces over the same query: `/webhooks/` renders the full page,
`/webhooks/search` renders just the rows fragment that HTMX swaps in. Phase 4
adds the ingestion endpoint that fills this table.
"""

from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.jobs import process_payload, soniq
from app.models.webhook import WebhookEvent
from app.schemas.webhook import WebhookEventPublic
from app.templating import templates

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


async def _recent(db: AsyncSession, q: str) -> list[WebhookEvent]:
    stmt = select(WebhookEvent).order_by(WebhookEvent.created_at.desc())
    if q:
        stmt = stmt.where(WebhookEvent.slug.ilike(f"%{q}%"))
    result = await db.execute(stmt.limit(50))
    return list(result.scalars().all())


@router.post("/{slug}", response_model=WebhookEventPublic, status_code=202)
async def ingest_webhook(
    slug: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
) -> WebhookEventPublic:
    """Record the payload, hand its id to a Soniq job, return 202 at once.

    The response is 202 (accepted, not processed): the work happens off the
    request path in `app.jobs.process_payload`.
    """
    event = WebhookEvent(slug=slug, payload=payload)
    db.add(event)
    await db.commit()
    await db.refresh(event)

    # AGENTS.md: enqueue a primitive id, never the ORM object.
    await soniq.enqueue(process_payload, event_id=str(event.id))

    return WebhookEventPublic.model_validate(event)


@router.get("/", response_class=HTMLResponse)
async def webhooks_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    events = await _recent(db, q="")
    return templates.TemplateResponse(
        request, "webhooks/list.html", {"events": events}
    )


@router.get("/search", response_class=HTMLResponse)
async def webhooks_search(
    request: Request,
    q: str = "",
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    events = await _recent(db, q=q)
    return templates.TemplateResponse(
        request, "_partials/webhook_rows.html", {"events": events}
    )
