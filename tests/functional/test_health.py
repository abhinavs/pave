from httpx import AsyncClient


async def test_health_ok(async_client: AsyncClient) -> None:
    resp = await async_client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {
        "status": "ok",
        "version": "0.0.1",
        "database": "ok",
    }
