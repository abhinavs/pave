from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.webhook import WebhookEvent


async def _seed(db: AsyncSession, slug: str) -> None:
    db.add(WebhookEvent(slug=slug, status="processed", payload={"k": "v"}))
    await db.commit()


async def test_webhooks_page_is_full_document_with_search(
    async_client: AsyncClient,
) -> None:
    resp = await async_client.get("/webhooks/")
    assert resp.status_code == 200
    body = resp.text
    assert "<html" in body.lower()
    # the live-search input is wired with the canonical HTMX trigger
    assert 'hx-get="/webhooks/search"' in body
    assert "keyup changed delay:300ms" in body


async def test_live_search_returns_partial_not_full_page(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed(db_session, "stripe-prod")

    resp = await async_client.get("/webhooks/search", params={"q": "stripe"})
    assert resp.status_code == 200
    body = resp.text
    # a fragment, not a whole page
    assert "<html" not in body.lower()
    assert "stripe-prod" in body


async def test_live_search_filters_out_non_matches(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed(db_session, "stripe-prod")

    resp = await async_client.get("/webhooks/search", params={"q": "zzzzzz"})
    assert resp.status_code == 200
    assert "stripe-prod" not in resp.text
