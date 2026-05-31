"""Prometheus metrics.

A starter that ships a `/metrics` endpoint earns its keep on day one: the
operator scraping the host sees request volume and latency without writing
any glue. Counters and the histogram live at module scope - the
prometheus-client library uses a process-global registry, so re-creating
them per request would either error on the second import or fork the
state. Module import is the right place to declare them.

Routes opt in by importing the symbol they want and calling it. The
middleware in this module handles the HTTP layer automatically: every
request increments the counter and observes the histogram, labelled by
method, route template, and response status.

Why the route template (`/blog/{slug}`) and not the raw path: a
cardinality explosion in Prometheus is a real incident, and `path=/blog/x`
+ `path=/blog/y` + ... is the canonical way to cause one. Starlette
exposes the matched route on `request.scope["route"]`; we fall back to
"unmatched" when the path did not resolve."""

import time
from collections.abc import Awaitable, Callable

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route
from starlette.types import ASGIApp

http_requests_total = Counter(
    "pave_http_requests_total",
    "HTTP requests handled, labelled by method, route template, and status.",
    labelnames=("method", "route", "status"),
)

http_request_duration_seconds = Histogram(
    "pave_http_request_duration_seconds",
    "HTTP request latency in seconds, by method and route template.",
    labelnames=("method", "route"),
    # Buckets tuned for a typical web app: sub-millisecond is noise,
    # over a few seconds is a separate problem the timeout will catch.
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)


def _route_template(request: Request) -> str:
    """Return the matched route's path template, or 'unmatched'.

    Using the template keeps label cardinality bounded - `/blog/{slug}`
    is one series no matter how many posts exist. We also strip the
    metrics endpoint itself out of the histogram via the middleware
    skip, so scraping does not pollute the latency distribution."""
    route = request.scope.get("route")
    if isinstance(route, Route):
        return route.path
    return "unmatched"


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Time every response, increment the counter, observe latency.

    We measure around `call_next` rather than instrumenting individual
    routes - one middleware covers every endpoint the app ever grows,
    including the ones a starter user adds tomorrow."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # Skip the metrics endpoint itself: scraping should not show up
        # as a request in its own output. (Also avoids a feedback loop
        # in the histogram if a scraper hits us aggressively.)
        if request.url.path == "/metrics":
            return await call_next(request)

        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start

        route = _route_template(request)
        http_requests_total.labels(
            method=request.method,
            route=route,
            status=str(response.status_code),
        ).inc()
        http_request_duration_seconds.labels(
            method=request.method,
            route=route,
        ).observe(elapsed)
        return response


def render(registry: CollectorRegistry = REGISTRY) -> bytes:
    """Serialize the registry to the Prometheus text exposition format."""
    return generate_latest(registry)


def install_metrics(app: ASGIApp) -> None:
    """Attach the middleware. The `/metrics` route is registered separately
    in `app/routers/metrics.py` so the route gate (settings.enable_metrics)
    can keep the endpoint off in environments that do not want it."""
    # mypy: ASGIApp does not declare add_middleware, but a Starlette/FastAPI
    # instance always does.
    app.add_middleware(PrometheusMiddleware)  # type: ignore[attr-defined]


__all__ = [
    "CONTENT_TYPE_LATEST",
    "http_request_duration_seconds",
    "http_requests_total",
    "install_metrics",
    "render",
]
