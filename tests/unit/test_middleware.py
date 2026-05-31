"""TrustedHostMiddleware wiring.

In production ALLOWED_HOSTS must actually reject requests carrying a foreign
Host header, otherwise host-header poisoning can redirect verification/reset
links to an attacker. When ALLOWED_HOSTS is the default ["*"] (dev), no host
filtering is installed.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware import install_middleware
from app.settings import settings


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/")
    def root() -> dict[str, bool]:
        return {"ok": True}

    install_middleware(app)
    return app


def test_unknown_host_is_rejected_when_hosts_configured(monkeypatch) -> None:
    monkeypatch.setattr(settings, "allowed_hosts", ["good.com"])
    monkeypatch.setattr(settings, "debug", True)  # keep CSRF out of the way
    app = _app()

    ok = TestClient(app, base_url="http://good.com").get("/")
    assert ok.status_code == 200

    bad = TestClient(app, base_url="http://evil.com").get("/")
    assert bad.status_code == 400


def test_wildcard_hosts_allows_any_host(monkeypatch) -> None:
    monkeypatch.setattr(settings, "allowed_hosts", ["*"])
    monkeypatch.setattr(settings, "debug", True)
    app = _app()

    resp = TestClient(app, base_url="http://anything.example").get("/")
    assert resp.status_code == 200
