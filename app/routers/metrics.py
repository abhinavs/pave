"""The /metrics endpoint.

Prometheus exposition format, no auth. The route is mounted from
`app/main.py` only when `settings.enable_metrics` is true: scraping is an
operational concern, and turning it on is a deliberate decision (you
need a firewall rule or a sidecar in front of it). The endpoint is
deliberately not under /api/ - Prometheus, Grafana Agent, and the
OpenTelemetry collector all expect /metrics by convention."""

from fastapi import APIRouter
from fastapi.responses import Response

from app.services.metrics import CONTENT_TYPE_LATEST, render

router = APIRouter(tags=["metrics"])


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(render(), media_type=CONTENT_TYPE_LATEST)
