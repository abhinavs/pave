"""The webhook demo: ingestion plus a table with HTMX live search.

Two surfaces over the same query: `/webhooks/` renders the full page,
`/webhooks/search` renders just the rows fragment that HTMX swaps in.
"""

import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.jobs import process_payload, soniq
from app.middleware import limiter
from app.models.webhook import WebhookEvent
from app.schemas.webhook import WebhookEventPublic
from app.settings import settings
from app.templating import templates

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

SIGNATURE_HEADER = "X-Webhook-Signature"
# Cap the body so a single request cannot exhaust memory or flood the table.
MAX_PAYLOAD_BYTES = 1 * 1024 * 1024  # 1 MiB


def _verify_signature(request: Request, raw: bytes) -> None:
    """Enforce the HMAC contract before any work is done.

    With a secret configured, the request must carry a matching SHA-256 HMAC
    of the raw body (constant-time compared). With no secret, ingestion is
    open only in debug: an unauthenticated endpoint in production is a
    DoS/injection vector, so it stays closed until WEBHOOK_SECRET is set.
    """
    secret = settings.webhook_secret
    if not secret:
        if settings.debug:
            return
        raise HTTPException(status_code=503, detail="webhook ingestion not configured")

    provided = request.headers.get(SIGNATURE_HEADER, "")
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="invalid webhook signature")


async def _recent(db: AsyncSession, q: str) -> list[WebhookEvent]:
    stmt = select(WebhookEvent).order_by(WebhookEvent.created_at.desc())
    if q:
        stmt = stmt.where(WebhookEvent.slug.ilike(f"%{q}%"))
    result = await db.execute(stmt.limit(50))
    return list(result.scalars().all())


@router.post("/{slug}", response_model=WebhookEventPublic, status_code=202)
@limiter.limit("60/minute")
async def ingest_webhook(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> WebhookEventPublic:
    """Record the payload, hand its id to a Soniq job, return 202 at once.

    The response is 202 (accepted, not processed): the work happens off the
    request path in `app.jobs.process_payload`.
    """
    raw = await request.body()
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise HTTPException(status_code=413, detail="payload too large")

    _verify_signature(request, raw)

    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")

    event = WebhookEvent(slug=slug, payload=payload)
    db.add(event)
    await db.commit()
    await db.refresh(event)

    # Enqueue a primitive id, never the ORM object (it is not serializable).
    await soniq.enqueue(process_payload, event_id=str(event.id))

    return WebhookEventPublic.model_validate(event)


@router.get("/", response_class=HTMLResponse)
async def webhooks_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    events = await _recent(db, q="")
    return templates.TemplateResponse(request, "webhooks/list.html", {"events": events})


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
