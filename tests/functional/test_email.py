"""send_email: console fallback when unconfigured, one POST when configured.

httpx is intercepted with a MockTransport so no real network is touched and
the exact request can be inspected.
"""

import httpx
import pytest

import app.email as email_mod
from app.email import EmailMessage, send_email


def _msg() -> EmailMessage:
    return EmailMessage(
        to="ada@example.com",
        subject="Confirm your email",
        html="<p>hello</p>",
        text="hello",
    )


async def test_unconfigured_uses_console_and_makes_no_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(email_mod.settings, "email_api_url", None)
    monkeypatch.setattr(email_mod.settings, "email_api_key", None)

    def _explode(*a: object, **k: object) -> None:
        raise AssertionError("send_email made an HTTP call when unconfigured")

    monkeypatch.setattr(email_mod.httpx, "AsyncClient", _explode)

    await send_email(_msg())  # must not raise: console path only


async def test_configured_makes_exactly_one_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        email_mod.settings, "email_api_url", "https://api.example.com/send"
    )
    monkeypatch.setattr(email_mod.settings, "email_api_key", "secret-key")
    monkeypatch.setattr(email_mod.settings, "email_from", "Pave <no@pave.dev>")

    requests: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(202, json={"ok": True})

    transport = httpx.MockTransport(_handler)
    real_client = email_mod.httpx.AsyncClient

    def _client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(email_mod.httpx, "AsyncClient", _client)

    await send_email(_msg())

    assert len(requests) == 1
    sent = requests[0]
    assert sent.method == "POST"
    assert str(sent.url) == "https://api.example.com/send"
    assert sent.headers["Authorization"] == "Bearer secret-key"
    body = sent.read().decode()
    assert "Confirm your email" in body
    assert "no@pave.dev" in body


async def test_configured_raises_on_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        email_mod.settings, "email_api_url", "https://api.example.com/send"
    )
    monkeypatch.setattr(email_mod.settings, "email_api_key", "secret-key")

    transport = httpx.MockTransport(
        lambda request: httpx.Response(500, text="boom")
    )
    real_client = email_mod.httpx.AsyncClient
    monkeypatch.setattr(
        email_mod.httpx,
        "AsyncClient",
        lambda *a, **k: real_client(*a, **{**k, "transport": transport}),
    )

    with pytest.raises(httpx.HTTPStatusError):
        await send_email(_msg())
