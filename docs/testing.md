# Testing

How tests are organized in Pave, the fixtures you actually use, and the
patterns that keep the suite fast and honest.

## The 30-second version

```bash
pave test         # full suite
pave lint         # ruff check
pave fmt          # ruff format
pave typecheck    # mypy app/
fab validate      # all of the above, plus migration checks
```

- `pytest-asyncio` is in auto mode. Tests are plain `async def test_...`
  functions. No `@pytest.mark.asyncio` decorator anywhere.
- Tests live under `tests/unit/`, `tests/functional/`, `tests/integration/`,
  `tests/ui/`. Pick the directory that matches what you are testing.
- Standard fixtures come from `tests/conftest.py`: `async_client`,
  `db_session`, `test_user`, `verified_user`, `authenticated_client`.
- The DB is in-memory SQLite, freshly created per test, never committed
  past the end of the test.

## The test layout

| Directory | What goes here |
|---|---|
| `tests/unit/` | Pure functions and small services. No HTTP, no app wiring. Use `db_session` only if the function under test takes one. |
| `tests/functional/` | One route, one job, or one HTMX surface at a time, through the real app and a real session. Most of the suite lives here. |
| `tests/integration/` | Structural and project-wide checks. Migrations apply cleanly, no ORM model is used as a `response_model`, deploy artifacts are present. These are the guardrails that catch drift between subsystems. |
| `tests/ui/` | Template and HTMX surface tests. Asserts on rendered HTML and partial responses (full page vs fragment, HTMX wiring attributes, error pages). No real browser, just HTML assertions on `async_client` responses. |

If you are writing a test and you cannot decide between `unit` and
`functional`, the rule of thumb is: does it call `async_client`? Then it is
functional. Does it only call a service or pure function? Then it is unit.

## Standard fixtures

All defined in `tests/conftest.py`. The schema is built and torn down
around every test by an autouse fixture, so each test starts from an empty
database.

| Fixture | What it is | When to use it |
|---|---|---|
| `db_session` | `AsyncSession` bound to the shared in-memory engine. Rolled back at the end of the test. | Any test that needs to read or seed the database directly. |
| `async_client` | `httpx.AsyncClient` wired to the FastAPI app via `ASGITransport`. `raise_app_exceptions=False` so unhandled errors flow through the registered 500 handler, the way they do in production. | Any test that exercises a route. |
| `test_user` | A created, unverified `User` (email `ada@example.com`, password `correct horse`). Committed so it is visible to the app. | Tests that need a user but do not require email verification. |
| `verified_user` | Same shape, but with `email_verified_at` set. Email `grace@example.com`. | Routes that require `require_verified_user`. |
| `authenticated_client` | `async_client` carrying a real session cookie minted via `create_session` for `test_user`. | Any route protected by `require_user`. |

There is no separate `mock_email` fixture. Outbound email is mocked
per-test with `monkeypatch` against `app.email`. See "Mocking outbound
email" below.

Note: `test_user` and `verified_user` both commit. That is fine. They run
inside fixture scope, and the autouse `_schema` fixture drops every table
at the end of each test, so nothing persists.

## Writing a route test

The POST + GET pattern. Hit the endpoint, then verify both the HTTP
response and the database state.

```python
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.webhook import WebhookEvent


async def test_post_webhook_stores_event_with_payload(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    payload = {"type": "issue.opened", "number": 7}

    resp = await async_client.post("/webhooks/github", json=payload)

    assert resp.status_code == 202
    body = resp.json()
    assert body["slug"] == "github"
    assert "password_hash" not in body  # output schema must not leak internals

    event = (
        await db_session.execute(
            select(WebhookEvent).where(WebhookEvent.slug == "github")
        )
    ).scalar_one()
    assert event.payload == payload
    assert event.status == "pending"
```

For routes that require authentication, use `authenticated_client`:

```python
async def test_account_page_renders_for_user(
    authenticated_client: AsyncClient,
) -> None:
    resp = await authenticated_client.get("/account")
    assert resp.status_code == 200
    assert 'action="/account/avatar"' in resp.text
```

And confirm the redirect behavior for unauthenticated access:

```python
async def test_account_page_requires_login(async_client: AsyncClient) -> None:
    resp = await async_client.get("/account")
    assert resp.status_code in (302, 303)
    assert "/auth/login" in resp.headers["location"]
```

## Writing a job test

Jobs in `app/jobs/` are pure async functions that take a session as a
parameter (see AGENTS.md, "Soniq jobs"). Test them by calling them
directly with `db_session`. Do not go through Soniq.

```python
import uuid
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.process_payload import process_payload
from app.models.webhook import WebhookEvent


async def test_process_payload_marks_event_processed(
    db_session: AsyncSession,
) -> None:
    event = WebhookEvent(slug="demo", payload={"hi": 1})
    db_session.add(event)
    await db_session.commit()

    await process_payload(event.id, db_session)
    await db_session.refresh(event)

    assert event.status == "processed"


async def test_process_payload_idempotent_on_missing_record(
    db_session: AsyncSession,
) -> None:
    # A job for a record that no longer exists is a no-op, not an error.
    await process_payload(uuid.uuid4(), db_session)
```

To prove that a route enqueues the right job with the right arguments,
fake `soniq.enqueue` with `monkeypatch` and inspect the recorded calls.
The functional webhook tests in `tests/functional/test_webhooks.py` show
the full pattern with an `_EnqueueRecorder` class.

## Asserting on the database

Always use `select()` from SQLAlchemy. The legacy `db.query(...)` API is
banned in app code and tests alike.

```python
from sqlalchemy import select

result = await db_session.execute(
    select(WebhookEvent).where(WebhookEvent.slug == "stripe")
)
event = result.scalar_one()                  # exactly one
maybe = result.scalar_one_or_none()           # zero or one
events = result.scalars().all()               # list
```

When a route mutates a row your test fixture already holds, call
`await db_session.refresh(obj)` before re-reading attributes. Otherwise
you see the stale in-session copy and your assertion will lie to you.

```python
await authenticated_client.post("/account/avatar", files=files)
await db_session.refresh(test_user)
assert test_user.avatar_url is not None
```

## Mocking outbound HTTP

Pave uses `httpx` everywhere. Mock at the transport, not the function.
`httpx.MockTransport` lets you inspect the exact request the code under
test produced.

```python
import httpx

import app.email as email_mod


async def test_configured_makes_exactly_one_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(202, json={"ok": True})

    transport = httpx.MockTransport(_handler)
    real_client = email_mod.httpx.AsyncClient
    monkeypatch.setattr(
        email_mod.httpx,
        "AsyncClient",
        lambda *a, **k: real_client(*a, **{**k, "transport": transport}),
    )

    await send_email(_msg())

    assert len(requests) == 1
    assert requests[0].method == "POST"
```

There is no `respx` dependency. `httpx.MockTransport` is enough, ships
with httpx, and forces you to interact at the request level, which is
where the bugs live.

When a test should assert that no HTTP call happens at all (for example,
the email module's console fallback when unconfigured), replace
`httpx.AsyncClient` with a function that raises:

```python
def _explode(*a: object, **k: object) -> None:
    raise AssertionError("send_email made an HTTP call when unconfigured")

monkeypatch.setattr(email_mod.httpx, "AsyncClient", _explode)
```

## Mocking outbound email

Email is a generic HTTP provider, not Resend. There is no `mock_email`
fixture. The pattern is the same as for any other outbound HTTP call:
patch `app.email.settings` to enable the provider, then intercept
`httpx.AsyncClient` with a `MockTransport`.

```python
import pytest

import app.email as email_mod
from app.email import EmailMessage, send_email


async def test_signup_sends_verification_email(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        email_mod.settings, "email_api_url", "https://api.example.com/send"
    )
    monkeypatch.setattr(email_mod.settings, "email_api_key", "secret-key")

    sent: list[httpx.Request] = []
    transport = httpx.MockTransport(
        lambda req: (sent.append(req), httpx.Response(202, json={"ok": True}))[1]
    )
    real_client = email_mod.httpx.AsyncClient
    monkeypatch.setattr(
        email_mod.httpx,
        "AsyncClient",
        lambda *a, **k: real_client(*a, **{**k, "transport": transport}),
    )

    resp = await async_client.post(
        "/auth/signup",
        data={"name": "Ada", "email": "ada@example.com", "password": "correct horse"},
    )

    assert resp.status_code in (200, 302, 303)
    assert len(sent) == 1
    assert "Confirm your email" in sent[0].read().decode()
```

If this pattern appears in three or more tests, lift it into a small
helper in your test module (not a global fixture - it keeps the
configuration explicit at the call site).

## Coverage and quality gates

Pave does not enforce a coverage percentage and does not chase one. What
matters is that every route and every job has at least one test that
exercises the happy path and at least one that pins the failure mode
that callers depend on (validation rejection, auth gate, idempotency,
not-found).

The four gates that run alongside `pave test`:

```bash
pave lint         # ruff check
pave fmt          # ruff format (use --check in CI, plain in dev)
pave typecheck    # mypy app/ in strict mode
pave test         # the suite
```

`fab validate` runs all of them, plus a clean migration apply. It is the deployment gate. Treat a green `fab validate` as the contract you ship against, not a green `pave test` on its own.

If `pave fmt` reformats your code, commit the reformatted version. Do
not argue with ruff. If `pave typecheck` fails on a third-party stub,
add a typed shim in `app/` rather than scattering `# type: ignore` at
the call sites.

## Common mistakes

- **Committing in a test.** The `db_session` fixture rolls back at the
  end of the test. If you `await db_session.commit()` and then expect
  the next test to see a clean slate, you are relying on the autouse
  schema fixture to drop tables, which works but is slower than
  necessary and obscures intent. Seed through fixtures, mutate through
  the route, assert through `select()`. Commit only when you need the
  row visible to a subsequent HTTP request that goes through
  `async_client` (the request gets its own session via the dependency
  override, so cross-session visibility requires a commit).
- **Forgetting `await`.** Every database call, every `async_client`
  call, every job invocation is `async`. A missing `await` returns a
  coroutine object that your assertion silently passes against. If a
  test passes too easily, check the `await`s first.
- **Using `requests` or sync `httpx.Client`.** Always use the
  `async_client` fixture. The app is async; a sync client will either
  hang or run the app on the wrong loop.
- **Hitting a protected route with `async_client`.** Use
  `authenticated_client` for anything behind `require_user` or
  `require_verified_user`. A bare `async_client` will get a 302 to
  `/auth/login` and your assertion against the page body will fail in
  ways that look unrelated.
- **Asserting on stale ORM state.** After a route mutates a row, call
  `await db_session.refresh(obj)` before re-reading.
- **Passing an ORM object to `soniq.enqueue`.** Jobs take primitive ids
  (see AGENTS.md). Tests that fake `enqueue` should assert the call was
  made with a UUID string, not an instance.
- **Real network calls leaking in.** If a test is slow or flaky,
  suspect an unmocked outbound call. The email module is the usual
  culprit. Patch `httpx.AsyncClient` for the module under test.

## What runs in CI vs locally

Locally, `pave test` is fast: in-memory SQLite, no network, no Soniq
worker, no Tailwind build. Run it on every save if you want.

CI and `fab validate` run the same `pave test` plus:

- `pave lint`, `pave fmt --check`, `pave typecheck`
- A clean Alembic upgrade from zero against a throwaway database
- The integration suite's structural checks (`tests/integration/`),
  which catch drift like an ORM model accidentally used as a
  `response_model`

If `fab validate` fails, fix it locally. Do not push hoping CI will be
kinder. The remote runs the same script.
