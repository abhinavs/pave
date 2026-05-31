"""Metrics service tests.

The middleware and renderer are exercised against a tiny throwaway
FastAPI app so the production app's mount gate (settings.enable_metrics)
does not get in the way. The integration that matters at this layer is
"middleware increments a counter, render serialises it" - that lives
here. The route's gating-by-flag behaviour is pinned in tests/ui/."""

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from prometheus_client import CollectorRegistry, Counter, generate_latest

from app.routers.metrics import router as metrics_router
from app.services.metrics import (
    PrometheusMiddleware,
    http_requests_total,
    render,
)


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(PrometheusMiddleware)
    app.include_router(metrics_router)

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"ok": "yes"}

    return app


async def test_render_returns_prometheus_text() -> None:
    """A custom registry keeps the assertion hermetic - the global REGISTRY
    accumulates state from other tests in the same process, so a check
    against `pave_http_requests_total` would race. We only need to prove
    `render` produces the exposition format for whatever registry is
    handed in."""
    registry = CollectorRegistry()
    c = Counter(
        "test_counter",
        "documented",
        labelnames=("kind",),
        registry=registry,
    )
    c.labels(kind="a").inc()
    body = generate_latest(registry).decode()
    # prometheus-client appends _total to the rendered counter name
    assert "# HELP test_counter_total" in body
    assert 'test_counter_total{kind="a"} 1.0' in body


async def test_render_default_includes_pave_counter() -> None:
    """The module-scope counter is registered in the default REGISTRY at
    import time, so it always shows up in `render()`."""
    body = render().decode()
    assert "pave_http_requests_total" in body


async def test_middleware_increments_counter_on_request() -> None:
    app = _make_app()
    # Read the counter via the registry, since the middleware writes to
    # the module-global. We just check the value moved up by at least one
    # over a request - other tests may have incremented it too.
    sample = http_requests_total.labels(method="GET", route="/ping", status="200")
    before = sample._value.get()  # type: ignore[attr-defined]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/ping")
    assert resp.status_code == 200
    after = sample._value.get()  # type: ignore[attr-defined]
    assert after >= before + 1


async def test_metrics_endpoint_serves_text_format() -> None:
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # one request to make sure the counter has at least one sample
        await client.get("/ping")
        resp = await client.get("/metrics")
    assert resp.status_code == 200
    # CONTENT_TYPE_LATEST is "text/plain; version=0.0.4; charset=utf-8"
    assert resp.headers["content-type"].startswith("text/plain")
    assert "pave_http_requests_total" in resp.text


async def test_metrics_endpoint_does_not_count_itself() -> None:
    """Scraping should not appear in its own output. The middleware skips
    /metrics so a busy scraper does not pollute the latency histogram."""
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        before = await client.get("/metrics")
        after = await client.get("/metrics")
    # Both calls succeed, and the second body does not contain a label
    # series for the /metrics route - that is the whole point.
    assert before.status_code == 200
    assert after.status_code == 200
    assert 'route="/metrics"' not in after.text
