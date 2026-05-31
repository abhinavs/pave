"""Error-page tests.

The handlers in app.errors render the templated 404/500 for browsers and
JSON for /api/ callers. We pin both contracts and the dev-only preview
routes - the latter exist so the design of the error pages can be
iterated on without engineering a real failure."""

from httpx import AsyncClient


async def test_unknown_url_returns_templated_404(async_client: AsyncClient) -> None:
    resp = await async_client.get("/this-route-does-not-exist")
    assert resp.status_code == 404
    body = resp.text
    assert "404" in body
    # The shared base layout is rendered, so the user's site context is
    # still on screen - footer links, header, etc.
    assert "<html" in body.lower()
    assert "/static/css/app.css" in body


async def test_api_404_stays_json(async_client: AsyncClient) -> None:
    """Anything under /api/ keeps the JSON contract even when missing."""
    resp = await async_client.get(
        "/api/does-not-exist", headers={"accept": "application/json"}
    )
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")


async def test_dev_preview_404_renders_template(async_client: AsyncClient) -> None:
    """The dev preview route is mounted because the test env runs with
    DEBUG=true (see conftest.py). It returns the 404 template at a 404
    status without going through the exception handler."""
    resp = await async_client.get("/dev/preview/404")
    assert resp.status_code == 404
    assert "could not find" in resp.text.lower()


async def test_dev_preview_500_triggers_handler(async_client: AsyncClient) -> None:
    """Raising inside the preview route exercises the production 500
    handler - we expect the templated page, not a stack trace."""
    resp = await async_client.get("/dev/preview/500")
    assert resp.status_code == 500
    body = resp.text
    assert "Something went wrong" in body
    # The reference chip is present because request-id middleware runs
    # before the handler, so the page has something to show.
    assert "Reference" in body or "request_id" in body
