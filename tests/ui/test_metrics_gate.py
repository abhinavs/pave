"""The /metrics endpoint is opt-in.

Conftest does not set ENABLE_METRICS, so the production app is built with
the flag off and the route is not mounted. Hitting /metrics in this
environment must 404 - that is the whole gate. The enabled path is
covered in tests/unit/test_metrics.py against a throwaway app."""

from httpx import AsyncClient


async def test_metrics_route_is_off_by_default(async_client: AsyncClient) -> None:
    resp = await async_client.get("/metrics")
    assert resp.status_code == 404
