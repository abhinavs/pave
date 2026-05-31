# Monitoring, logs, and observability

This page covers what Pave watches in production, where the signals live, and how to read them when something is off. The defaults are intentionally small: a health endpoint, structured logs in journald, and two optional integrations (Sentry, Prometheus). Add more only when you have a question the defaults cannot answer.

## The 30-second version

- Liveness: `GET /health` returns `{"status": "ok" | "degraded", "version": "...", "database": "ok" | "error"}`. Use it for uptime monitors and the deploy gate.
- Logs: structured (JSON in prod, pretty in dev) on stdout. Captured by systemd. `fab logs` tails `pave-api`. Every request gets a correlation id surfaced as the `X-Request-ID` response header and in the log line for the error.
- External probe: `.github/workflows/health-probe.yml` runs every 10 minutes and opens a sev-1 issue (and pings Webhooq) on failure.
- Optional: set `SENTRY_DSN` for error tracking. Set `ENABLE_METRICS=true` to expose `/metrics` for Prometheus.

If you are pager-debugging right now, jump to [Common questions](#common-questions).

---

## `/health`

Implemented in `app/routers/health.py`. The default check pings the database and reports the app version:

```python
@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    try:
        await db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "version": settings.app_version,
        "database": db_status,
    }
```

The endpoint always returns HTTP 200, even when degraded. The `status` field in the body is the signal. Any external monitor that only checks status code will miss a database outage where the API process itself is fine. The deploy gate and the scheduled probe both use `vrk assert '.status == "ok"'` for this reason.

### Adding deeper checks

Edit `app/routers/health.py`. Keep the contract: return 200 with `status` set to `"ok"` or `"degraded"`. Examples of things people commonly add:

- Soniq queue depth. Add a `SELECT count(*) FROM soniq_jobs WHERE status = 'pending'` and mark degraded above a threshold.
- An external dependency reach test (the email provider, a third-party API). Bound it with a short timeout, do not block `/health` on someone else's outage.
- Disk free. Pull it from `shutil.disk_usage` and flag below a threshold.

One thing not to add: anything that itself can hang for more than a second or two. `/health` is hit by uptime monitors every 30 to 60 seconds. A slow check turns into a slow alert.

---

## Structured logs

Configured in `app/logging.py`. structlog is the only logger, and every log line carries:

- `event` - the message
- `level` - debug / info / warning / error
- `timestamp` - ISO-8601, UTC
- Plus whatever keyword args the call site passed (`path`, `method`, `request_id`, etc.)

In `DEBUG=true` (local dev) the renderer is `structlog.dev.ConsoleRenderer` - human-readable, colorized. In production it is `structlog.processors.JSONRenderer` - one JSON object per line, ready for `jq` or any log shipper.

### Request IDs

`app/middleware.py` adds a `RequestIDMiddleware` that:

1. Reads `X-Request-ID` from the request, or generates a fresh `uuid4().hex` if absent.
2. Stores it on `request.state.request_id`.
3. Echoes it back on the response as `X-Request-ID`.

The 500 handler in `app/errors.py` logs uncaught exceptions with that `request_id`. The HTML 500 page renders the same id, so a user can paste it into a bug report and you can grep the logs.

A line from a 500 looks roughly like:

```json
{"event": "unhandled exception", "level": "error", "timestamp": "2026-05-27T14:03:12Z", "path": "/items/42", "method": "GET", "request_id": "a1b2c3d4e5f6..."}
```

Routes that want to attach more context call `structlog.contextvars.bind_contextvars(...)` so subsequent logs in the same request pick it up automatically.

### What gets logged

- Startup and shutdown (`app/main.py` lifespan).
- Unhandled exceptions in routes (via the 500 handler in `app/errors.py`).
- Anything route or job code explicitly logs.

What does not get logged by default:

- A line per request. There is no access log middleware. Add one if you need it, but Prometheus (`pave_http_requests_total`) and journald give you most of what an access log is for.
- Request bodies. They often contain secrets.

---

## Reading logs in production

Both services log to journald via systemd. The units live in `deploy/`:

- `pave-api.service` - the Gunicorn/uvicorn process
- `pave-worker.service` - the Soniq worker

### Tailing from your laptop

```bash
fab production logs                     # tail pave-api, last 100 lines, then follow
fab production logs --service pave-worker
fab production logs --lines 500
```

`fab logs` is a thin wrapper around `sudo journalctl -u <service> -n <lines> -f` over SSH.

### On the host

Once you are SSHed in (`fab production ssh`):

```bash
# Tail the API, follow new lines
sudo journalctl -u pave-api -f

# Last hour
sudo journalctl -u pave-api --since "1 hour ago"

# Since yesterday
sudo journalctl -u pave-api --since yesterday

# Just errors and worse
sudo journalctl -u pave-api -p err

# A specific request id (the X-Request-ID a user pasted in a bug report)
sudo journalctl -u pave-api --since "1 hour ago" | grep a1b2c3d4

# Pretty-print JSON one event per line
sudo journalctl -u pave-api -o cat --since "1 hour ago" | jq .

# Count errors in the last hour, grouped by path
sudo journalctl -u pave-api -p err --since "1 hour ago" -o cat \
  | jq -r '.path' | sort | uniq -c | sort -rn
```

The `-o cat` output mode strips the journald prefix and leaves just your JSON payload, which is what `jq` wants.

---

## Sentry (optional, recommended for production)

Set `SENTRY_DSN` in `.env.production` and uncaught exceptions are forwarded to Sentry. The env var is declared in `app/settings.py` as `sentry_dsn` and listed `optional` in `.env.schema`. Leaving it unset is a supported configuration - Pave does not need Sentry to run.

The Sentry SDK hooks into the FastAPI app and the Soniq worker at startup. You get:

- Uncaught exceptions in route handlers, with the request id, path, method, and user (if a session is present).
- Uncaught exceptions in jobs, with the job name and arguments.
- Stack traces with local variables (subject to Sentry's PII settings - review them).

What Sentry will not catch on its own:

- Handled errors. If your code does `except Exception: log.warning(...)`, that is by design not an alert.
- Expected 4xx responses. A 404 is not a Sentry event, it is a fact about the internet. The 500 handler in `app/errors.py` is the trigger.
- A wholly-down server. The process being down means the SDK is also down. That is what the external probe is for.

Run a deliberate test exception once after enabling: visit `/dev/preview/500` in a debug build, or curl a route you know throws, and confirm the event lands.

---

## Prometheus (`/metrics`)

`app/services/metrics.py` ships a Prometheus middleware that is always attached, so counters and histograms accumulate from process start. The `/metrics` route itself is gated:

```bash
ENABLE_METRICS=true
```

When `enable_metrics` is true, `app/main.py` mounts `app/routers/metrics.py` at `/metrics`. The route returns the registry in the standard text exposition format. There is no auth on the endpoint - put a firewall rule, an nginx `allow`/`deny` block, or a private network in front of it before turning it on.

### What ships

```
pave_http_requests_total{method, route, status}
    Counter. Incremented once per response.

pave_http_request_duration_seconds{method, route}
    Histogram. Latency in seconds, buckets at
    [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0].
```

The `route` label is the matched route template (`/blog/{slug}`), not the raw path. Cardinality explosions in Prometheus are real, and labelling by raw URL is the canonical way to cause one. Unmatched paths report as `route="unmatched"`.

The `/metrics` endpoint itself is excluded from its own histogram so scraping does not pollute the latency distribution.

### Adding your own metrics

Import the counter or histogram from `app.services.metrics` (or declare your own at module scope - prometheus-client uses a process-global registry). Call `.labels(...).inc()` or `.observe(...)` from a route or job. Keep label sets small.

---

## The scheduled health probe

`.github/workflows/health-probe.yml` runs on GitHub-hosted runners.

- Schedule: `*/10 * * * *` (every 10 minutes).
- Also dispatchable from the Actions UI with an optional `domain` override.
- Installs `vrk`, runs `vrk coax --times 6 --backoff exp:500ms -- vrk grab https://<domain>/health | vrk assert '.status == "ok"'`.

On failure:

1. Files (or reuses) a GitHub issue labelled `sev-1, health-probe`. The same labels mean a single open issue, not a new one per run.
2. POSTs `{"event": "health.degraded", "domain": "...", "run_id": "..."}` to the `WEBHOOQ_URL` secret, if configured.

This is the **external** arm of monitoring. It runs off your servers, on GitHub's network, and catches the case where your box is wholly down (Sentry and the in-app metrics cannot tell you that, by definition). It is the cheap, branded version of an uptime monitor. The recommendation is still to point a third-party uptime monitor at `/health` too (see [External uptime monitoring](#external-uptime-monitoring)) - GitHub Actions is not a paging product.

---

## Deploy-time health probe

`fab production deploy` runs the same probe after the symlink flip and service restart:

```python
vrk coax --times 5 --backoff exp:200ms -- \
  vrk grab https://{domain}/health | \
  vrk assert '.status == "ok"' --message 'deploy failed health check'
```

Same shape as the scheduled probe, tighter retries because the deploy is interactive. Failure after all retries triggers an automatic rollback: the `current` symlink flips back to the previous release, services restart, and `fab deploy` exits non-zero. The bad release directory is kept on disk for postmortem.

This is why `/health`'s `status` field exists. Returning a 200 with `status="degraded"` lets the new release boot, get scraped, and serve light traffic without passing the gate.

---

## `WEBHOOQ_ENDPOINT` (deploy events)

Optional. When set, `fab deploy` POSTs `{"event": "deploy.success", "release": "<id>"}` to the endpoint after a successful health check:

```python
def _emit_deploy_event(release: str) -> None:
    endpoint = settings.webhooq_endpoint
    if not endpoint:
        return
    try:
        httpx.post(endpoint, json={"event": "deploy.success", "release": release}, timeout=5)
    except Exception:
        pass
```

Errors are swallowed. The deploy already succeeded by this point; a flaky sink is not allowed to fail it after the fact. Treat the event stream as best-effort: a deploy can succeed without an event landing. Use it to drive a release feed, an internal dashboard, or a Slack post. Do not use it as the source of truth for "did this deploy ship?".

The CI health probe uses a separate `WEBHOOQ_URL` repo secret for the `health.degraded` notification. They can point at the same sink or different ones - the events are distinguishable by the `event` field.

---

## External uptime monitoring

The CI probe runs every 10 minutes and only notifies via GitHub Issues and Webhooq. That is fine as a baseline; it is not a substitute for a real uptime monitor.

Set up one of UptimeRobot, Better Stack, Pingdom, or equivalent. Configure:

- URL: `https://your-domain/health`
- Method: GET
- Expected status: 200
- Optional: keyword check for `"status":"ok"` in the response body. Without this, a degraded server that still answers will not alert.
- Interval: 1 to 5 minutes.
- Notification channels: SMS, email, your on-call rotation.

`fab production setup-monitoring` prints the URL to register and verifies the endpoint is currently reachable. It does not install anything on the host - external monitoring must run off-host by definition.

---

## Log retention

journald is the only log store. `fab setup-log-rotation` configures the cap:

```bash
SystemMaxUse=500M
```

in `/etc/systemd/journald.conf`. Past that, oldest journal files are evicted. On a quiet server, 500M is several weeks of logs; on a chatty one it might be a day. Bump it if you have disk. See `docs/deploy.md` for the full setup task.

If you want long-term retention, ship logs off-host. Add a journald exporter (`systemd-journal-upload`, Vector, Promtail) and route them to your log sink of choice. Pave does not bundle one because the right answer depends on your stack.

---

## Common questions

### How do I see all errors in the last hour?

```bash
fab production ssh
sudo journalctl -u pave-api -p err --since "1 hour ago" -o cat | jq .
```

If Sentry is configured, the Issues view in Sentry is faster - it groups by stack trace.

### How do I find a specific request?

A user gave you a request id (the `X-Request-ID` header, or the id printed on the 500 page). On the host:

```bash
sudo journalctl -u pave-api --since "2 hours ago" | grep <request-id>
```

### How do I trace a user's flow across requests?

There is no built-in tracing. Two practical options:

- Bind the user id into the structlog context at the start of each request, then grep journald by that id. Add `structlog.contextvars.bind_contextvars(user_id=str(user.id))` in a dependency that already runs (e.g. `require_user`).
- For real distributed tracing across services, add OpenTelemetry. The Prometheus middleware in `app/services/metrics.py` is a fine pattern to copy for OTel.

### How do I know if the worker is healthy?

The worker is a separate systemd unit and does not have its own HTTP endpoint. Signals to check:

```bash
sudo systemctl status pave-worker
sudo journalctl -u pave-worker --since "10 minutes ago" -p warning
```

For a real signal, add a Soniq queue-depth check to `/health` and alert on it crossing a threshold. Sentry will also fire on uncaught exceptions inside jobs.

### Did the last deploy actually succeed?

```bash
fab production ssh
ls -lt /srv/pave/releases/ | head -5
readlink /srv/pave/current
```

The newest directory under `releases/` is the last *attempted* deploy. The target of `/srv/pave/current` is the last *successful* one. If they differ, the most recent deploy rolled back. The journald entry for `pave-api` at that timestamp will say why.

### `/health` returns 200 but `status` is `"degraded"`. What now?

Look at the other fields in the body. The default check reports `database`; degraded with `database: "error"` means the API process is up but the database connection is failing. Check the DB host, the connection string in `.env.production`, and `pg_isready` on the database host. The deploy gate, the scheduled probe, and any uptime monitor configured with the keyword check will all be alerting in parallel.
