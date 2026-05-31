# Outbound email

Pave sends transactional email (verification links, password resets, future welcome messages) through a tiny generic HTTP module. There is no provider SDK, no Node build step for templates, and no setup required in development.

## The 30-second version

- One module: `app/email.py`. It POSTs JSON to whatever endpoint you set.
- No SDK. Any provider that accepts a Bearer-authed JSON POST works: Resend, Postmark, SendGrid, Mailchannels, your own SMTP-to-HTTP shim.
- When `EMAIL_API_KEY` or `EMAIL_API_URL` is unset, `send_email` logs the full payload as JSON and returns. That is the default for a fresh clone and for the test suite, so local dev needs zero email configuration.
- Real sends always happen from a Soniq job, never from a route handler.

If you are wondering why Pave is not on Resend's SDK: every transactional provider exposes the same five fields (`from`, `to`, `subject`, `html`, `text`) behind a POST. Tying the codebase to one vendor's client buys nothing but a migration when pricing changes.

## Configuration

Three environment variables, all already wired into `.env.example`, `.env.schema`, and `app/settings.py`:

| Variable | Required | Purpose |
|---|---|---|
| `EMAIL_API_URL` | No (optional) | The provider's send endpoint. Unset means console fallback. |
| `EMAIL_API_KEY` | No (optional) | Bearer token passed as `Authorization: Bearer <key>`. |
| `EMAIL_FROM` | No (defaults to `Pave <noreply@usepave.dev>`) | The `From` header. Must be a domain you have verified with the provider. |

A typical production `.env`:

```
EMAIL_API_URL=https://api.resend.com/emails
EMAIL_API_KEY=re_xxxxxxxxxxxxxxxxxxxx
EMAIL_FROM=Acme <noreply@acme.com>
```

In development, leave all three unset. You should see entries like this in the dev server log when something tries to send:

```
email.console  to=ada@example.com  subject="Confirm your email"  message={"from": "...", "to": "...", ...}
```

Verification links are right there in the JSON, so signup-and-verify flows work end to end with no provider account.

## Sending from a job

Email always goes through Soniq. The route mints any tokens it needs, enqueues a job with primitive identifiers, and returns. The job opens its own session, re-reads the user, renders the templates, and calls `send_email`.

The canonical example is `app/jobs/send_verification_email.py`. Read it once; it is short:

```python
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import create_verification_token
from app.email import render_email, send_email
from app.models.user import User


async def send_verification_email(
    user_id: uuid.UUID, verify_base_url: str, db: AsyncSession
) -> None:
    user = await db.get(User, user_id)
    if user is None:
        return
    if user.email_verified_at is not None:
        return

    token = create_verification_token(user.id)
    verify_url = f"{verify_base_url.rstrip('/')}/auth/verify?token={token}"
    await send_email(
        render_email(
            "verification",
            subject="Confirm your email",
            to=user.email,
            verify_url=verify_url,
        )
    )
```

Two helpers do all the work:

- `render_email(template, *, subject, to, **context) -> EmailMessage` reads `templates/email/{template}.html` and `.txt`, renders both with the Jinja context, and returns an `EmailMessage` dataclass.
- `send_email(msg: EmailMessage) -> None` posts the payload (or logs it in dev). It raises `httpx.HTTPStatusError` on a provider 4xx/5xx, which is exactly what you want under a queue: Soniq retries with backoff.

Writing a new job follows the same shape. Create `app/jobs/send_welcome.py`, take a `user_id` plus a session, render a template, send. Then register it by importing it in `app/jobs/__init__.py`.

## Sending from a route (do not)

Do not call `send_email` directly from a route handler. Enqueue a job instead:

```python
await soniq.enqueue(
    send_verification_email,
    user_id=user.id,
    verify_base_url=str(request.base_url),
)
```

Three reasons this rule is non-negotiable:

1. **Latency coupling.** A signup that awaits the provider also waits on the provider's worst case. A 4-second send blocks the request for 4 seconds.
2. **Error semantics.** A 500 from the provider becomes a 500 from your route, even though the user row was already committed. The user thinks signup failed when it succeeded.
3. **No retries.** A transient provider blip during a request is a lost email forever. The same blip during a Soniq job costs a few seconds and a retry.

The pattern is always: commit the row, enqueue the job, return the response.

## Templates

Email templates live in `templates/email/`, one folder per project, two files per message:

```
templates/email/
  verification.html
  verification.txt
  password_reset.html
  password_reset.txt
```

Both parts are hand-written Jinja. The `.html` part is bulletproof table-based markup that survives Outlook and Gmail clipping; the `.txt` part is the plain-text alternative every spam filter still rewards. There is no MJML compiler, no Node dependency, no build step. If you want to share a layout, use Jinja's `{% extends %}` between files in the same folder.

`render_email` always renders both. The provider receives both. Do not skip the text part.

## Testing

There is no `mock_email` fixture, because there does not need to be one. By default the test environment has `EMAIL_API_URL` and `EMAIL_API_KEY` unset, so `send_email` goes down the console-fallback path and makes zero HTTP calls. Tests that only need to confirm "an email was attempted" can just check that the route succeeded.

When a test actually needs to inspect the outgoing request, intercept httpx with a `MockTransport`. The pattern is in `tests/functional/test_email.py`:

```python
import httpx
import app.email as email_mod
from app.email import send_email, EmailMessage


async def test_sends_one_post(monkeypatch):
    monkeypatch.setattr(email_mod.settings, "email_api_url", "https://api.example.com/send")
    monkeypatch.setattr(email_mod.settings, "email_api_key", "secret-key")

    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(202, json={"ok": True})

    transport = httpx.MockTransport(handler)
    real_client = email_mod.httpx.AsyncClient
    monkeypatch.setattr(
        email_mod.httpx,
        "AsyncClient",
        lambda *a, **k: real_client(*a, **{**k, "transport": transport}),
    )

    await send_email(EmailMessage(to="ada@example.com", subject="Hi", html="<p>hi</p>", text="hi"))

    assert len(requests) == 1
    assert requests[0].headers["Authorization"] == "Bearer secret-key"
```

You should see: one POST, the exact headers and body you expect, no real network. The existing tests cover the console path, the configured-success path, and the configured-error path. Copy from them.

If you add a `mock_email` fixture later, put it in `tests/conftest.py` and have it return the captured request list. Until then, the three-line monkeypatch above is enough.

## Switching providers

It is an env var change. No code change.

| Provider | `EMAIL_API_URL` | Notes |
|---|---|---|
| Resend | `https://api.resend.com/emails` | Bearer-auth, accepts `{from, to, subject, html, text}` verbatim. Verify the sending domain in their dashboard first. |
| Postmark | `https://api.postmarkapp.com/email` | Uses an `X-Postmark-Server-Token` header instead of `Authorization: Bearer`. If you switch to Postmark, change the one header line in `app/email.py` and you are done. Field names match. |
| SendGrid | `https://api.sendgrid.com/v3/mail/send` | Bearer-auth. Its payload nests `personalizations` and `content`; you would adapt `build_payload` to that shape. The rest of the module is unchanged. |
| Generic (your own shim) | Whatever you serve | If you front the provider with your own service, just make it accept the default payload and you change nothing in Pave. |

The honest version: Resend is a one-liner. Postmark is a header swap. SendGrid wants a different body shape, so `build_payload` gains a six-line adaptation. That is the worst case and it is still smaller than installing one SDK.

## Common mistakes

- **Calling `send_email` from a route.** See "Sending from a route" above. Enqueue a job.
- **`EMAIL_FROM` domain does not match the verified sender at the provider.** Resend, Postmark, and SendGrid all reject sends from unverified domains with a 4xx that Soniq will retry into the ground. Verify the domain (SPF, DKIM, sometimes DMARC) in the provider dashboard before flipping the env vars.
- **Skipping the `.txt` template.** Plain text is not optional. Gmail and corporate filters score multipart messages higher than HTML-only.
- **Reading the user row in the route and passing fields to the job.** Pass `user_id`, let the job fetch. Otherwise a row that changes between enqueue and run sends stale data.
- **Expecting the dev environment to deliver real mail.** It does not, by design. If you need real delivery in development, set the three env vars to a sandbox account. Mailtrap or a Resend test API key both work.
- **Treating `email.console` log lines as errors.** They are not. They are the console fallback doing its job.

## What to build next

- A `send_welcome` job that fires after `email_verified_at` is set. Same shape as `send_verification_email`, different template.
- Bounce and complaint webhooks. Most providers POST to a URL you own when a recipient hard-bounces or marks the message as spam. Pave already ships a webhook router; one new handler in `app/routers/webhooks.py` plus a `mark_email_undeliverable` job and you have suppression handling.
- A `mock_email` fixture in `tests/conftest.py` once you have more than three tests that need to inspect outgoing email. Lift the monkeypatch block from `tests/functional/test_email.py` and yield the captured request list.
