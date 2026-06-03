# Background Jobs

Some work cannot happen on the request path. Sending an email through a flaky third party, processing a webhook payload, transcoding a file, calling a slow API: any of these can take seconds, fail, and need a retry. Doing them inside a route means your user waits and your error budget burns.

Pave ships **Soniq**, an offline job queue backed by your existing database. It is small, durable, and good enough for most real workloads.

## When to use a job

Use a job when the work fits one of these shapes:

- **Slow.** Anything over 200ms that the user does not need to wait for.
- **Flaky.** Calls to third parties that need retries with backoff.
- **Bursty.** Webhook ingestion: respond 202 fast, process behind a queue.
- **Periodic.** Until native scheduling lands, run periodic work from a systemd timer that calls a `pave` subcommand.

Do not use a job for: data you need to return in the same response, work measured in milliseconds, or anything where "ran twice" is dangerous and you have not designed for idempotency.

## The two jobs that ship with Pave

Both are in `app/jobs/`. Reading them is the fastest way to understand the pattern.

| Job | Triggered by | Why it is offline |
|---|---|---|
| `process_payload` | `POST /webhooks/{slug}` | Webhook receivers must 202 fast. Processing can be slow or fail and retry. |
| `send_verification_email` | `POST /auth/signup`, `POST /auth/resend` | Signup latency cannot depend on the email provider's worst case. Retries cover transient 5xxs. |

Both follow the same shape, which is what the rest of this page documents.

---

## Anatomy of a job

A job is one async function in `app/jobs/`. Create `app/jobs/send_welcome.py`:

```python
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.email import send_email


async def send_welcome(user_id: uuid.UUID, db: AsyncSession) -> None:
    """Send a welcome email after a user verifies their address."""
    user = await db.get(User, user_id)
    if user is None:
        return  # idempotent: the user might have been deleted

    await send_email(
        to=user.email,
        subject="Welcome",
        html=f"<p>Hi {user.name}, glad to have you.</p>",
    )
```

The contract:

- **Async function.** Soniq runs jobs in the same event loop as the worker.
- **Takes ids, not ORM objects.** ORM objects are not serialisable. The job fetches what it needs from the database.
- **Takes a session as its last argument.** The Soniq adapter in `app/jobs/__init__.py` opens a per-job session and passes it in. You never construct a session inside a job.
- **No return value.** A job either succeeds (returns) or fails (raises). The queue handles the rest.

Register the job by importing it in `app/jobs/__init__.py` so the adapter sees it:

```python
from app.jobs.send_welcome import send_welcome  # noqa: F401
```

> The session-opening adapter in `app/jobs/__init__.py` is the only sanctioned place outside a request handler where an `AsyncSession` is constructed. Do not inline a session into a job, and do not open one elsewhere in `app/jobs/`. See `AGENTS.md` for the rule and the reasoning.

---

## Enqueueing from a route

Inside any route handler:

```python
from app.jobs import send_welcome, soniq

@router.post("/auth/verify")
async def verify_email(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    user = await mark_verified(db, token)
    await soniq.enqueue(send_welcome, user_id=str(user.id))
    return {"status": "ok"}
```

`soniq.enqueue` writes a row to the queue table and returns immediately. The route responds at request speed; the job runs whenever the worker picks it up (usually within a second).

**Never pass ORM objects:**

```python
# Wrong
await soniq.enqueue(send_welcome, user=user)

# Right
await soniq.enqueue(send_welcome, user_id=str(user.id))
```

`AGENTS.md` enforces this; the runtime error otherwise is loud and unhelpful.

---

## Running the worker

**Local development:**

```bash
pave worker
```

That runs one worker process in the foreground. If you are iterating on a job, this is the terminal to keep open. Restart it when the code changes (no hot reload for workers).

**Production:**

The systemd unit `pave-worker.service` ships with the repo and is installed during VPS prep ([deploy.md](deploy.md)). It runs the same `pave worker` command under systemd supervision, restarting on crash, with logs to journald.

```bash
sudo systemctl status pave-worker
journalctl -u pave-worker -f
```

One worker is enough for most apps. To scale, run multiple worker units; Soniq's row-level locking prevents two workers from picking up the same job.

---

## Retries and failure

Soniq retries failed jobs with exponential backoff. A job is considered failed if it raises any exception. To force a retry deliberately (for example, after a 503 from an upstream API), just `raise`. To give up early (for example, an unrecoverable 4xx), catch the error inside the job and log it instead of raising.

```python
async def send_welcome(user_id: uuid.UUID, db: AsyncSession) -> None:
    user = await db.get(User, user_id)
    if user is None:
        return  # gone; nothing to retry

    try:
        await send_email(to=user.email, subject="...", html="...")
    except UnrecoverableEmailError as e:
        log.warning("dropping welcome email", user_id=user_id, reason=str(e))
        return
    # any other exception bubbles up and Soniq retries with backoff
```

After the maximum attempts the job is marked failed and surfaced in the worker log; you can re-enqueue it manually after fixing the underlying issue.

---

## Testing a job

Jobs are pure async functions, so you test them directly:

```python
from app.jobs.send_welcome import send_welcome


async def test_send_welcome_sends_email(db_session, verified_user, mock_email):
    await send_welcome(verified_user.id, db_session)

    assert mock_email.sent == [
        {"to": verified_user.email, "subject": "Welcome"}
    ]


async def test_send_welcome_silent_when_user_deleted(db_session, mock_email):
    fake_id = uuid.uuid4()
    await send_welcome(fake_id, db_session)
    assert mock_email.sent == []
```

The `db_session` fixture wraps each test in a rolled-back transaction. The `mock_email` fixture swaps the real HTTP email client for an in-memory recorder. See [testing.md](testing.md) for the full fixture catalogue.

To test the enqueue side (that a route actually enqueues a job), assert on the queue table after calling the route. The exact table name and import path live in `app/jobs/__init__.py`.

---

## Why not Celery?

Celery is great. It is also a lot: a broker (Redis or RabbitMQ), a result backend, a configuration surface, and operational quirks that you learn by hitting them in production.

Soniq trades scale for simplicity:

| | Soniq | Celery |
|---|---|---|
| Broker | Your existing Postgres | Redis or RabbitMQ |
| Setup | None (`pave setup` does it) | Install + configure + monitor a broker |
| Throughput | Real-app workloads (hundreds per second comfortably) | Tens of thousands+ |
| Scheduled jobs | Use a systemd timer for now | Celery Beat |
| Best for | The 95% case | High-throughput pipelines |

If you genuinely process millions of jobs a day, you will outgrow Soniq. Until then, the simplest queue is the one you do not have to operate.

---

## What to build next

- **Send email from a job** -> [email.md](email.md) covers the generic HTTP provider.
- **Process a webhook** -> read `app/jobs/process_payload.py` and the matching route in `app/routers/webhooks.py`.
- **See what is in the queue** -> `pave console`, then query the Soniq job table directly.
