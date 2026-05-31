# Configuration

Pave reads configuration from a single `.env` file (local) or `.env.production` (server). The file is parsed by `app/settings.py` using Pydantic Settings, so every variable is typed and validated at startup. Missing required values fail fast.

The schema is documented in `.env.schema`.

## The three-place rule

Every setting has a home in three places. Adding a setting in one and skipping the others breaks the deploy gate:

| File | Purpose |
|---|---|
| `.env.example` | Documents the variable with a comment and example value |
| `.env.schema` | Declares it `required` or `optional:default` |
| `app/settings.py` | Typed field on the `Settings` class |

`AGENTS.md` codifies this. Missing required settings fail fast at Pydantic startup.

---

## The variables

### Required

| Name | Type | Description |
|---|---|---|
| `DATABASE_URL` | postgres URL | `postgresql://user:pass@host/dbname`. SQLite supported via `USE_SQLITE=true` for local only. |
| `SONIQ_DATABASE_URL` | postgres URL | Job queue database. Usually the same as `DATABASE_URL`. |
| `SECRET_KEY` | string (48+ bytes recommended) | Signs session cookies and tokens. Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `ALLOWED_HOSTS` | comma list | Hostnames allowed in production: `usepave.dev,www.usepave.dev`. Set to `*` only in local dev. |

### Optional

| Name | Default | Description |
|---|---|---|
| `USE_SQLITE` | `false` | Use a local SQLite file under `var/` instead of Postgres. Local development only. |
| `DEBUG` | `false` | Enables `/api/docs`, plain log rendering, and disables the `Secure` cookie flag. `true` is for dev only. |
| `LOG_LEVEL` | `info` | One of `debug`, `info`, `warning`, `error`. |
| `GOOGLE_CLIENT_ID` | unset | Enables Google OAuth when set with the secret. |
| `GOOGLE_CLIENT_SECRET` | unset | See above. |
| `GITHUB_CLIENT_ID` | unset | Enables GitHub OAuth when set with the secret. |
| `GITHUB_CLIENT_SECRET` | unset | See above. |
| `EMAIL_API_KEY` | unset | Outbound email provider key. Unset = email logged to console as JSON. |
| `EMAIL_API_URL` | unset | Provider HTTP endpoint. |
| `EMAIL_FROM` | `Pave <noreply@usepave.dev>` | From-address for outbound mail. |
| `SENTRY_DSN` | unset | Error tracking. Unset = Sentry disabled. |
| `ENABLE_METRICS` | `false` | Exposes `/metrics` for Prometheus when `true`. |
| `AVATAR_DIR` | `static/uploads/avatars` | Where uploaded avatars are written. In production, point at a volume outside the release directory so deploys do not erase uploads. |
| `AVATAR_MAX_BYTES` | `4194304` | 4 MB. Larger uploads are rejected. |
| `WEBHOOQ_ENDPOINT` | unset | Best-effort POST of `deploy.success` events. |

---

## Adding a variable

Four places, in this order:

1. `.env.example` - a sensible default and a one-line comment.
2. `.env.schema` - mark required or optional, with a default.
3. `app/settings.py` - a typed field on the `Settings` class.
4. `docs/config.md` (this file) - a row in the table above.

`fab validate` will fail the next deploy until all three of the first three places are in sync. The fourth is on you; CI cannot catch missing docs.

---

## Environment-specific files

| File | Loaded in | Committed? |
|---|---|---|
| `.env.example` | Reference only | Yes |
| `.env.schema` | Reference and test assertion | Yes |
| `.env` | Local dev (via `pydantic-settings`) | No (gitignored) |
| `.env.production` | Production server only | No (placed manually) |

The systemd units `pave-api.service` and `pave-worker.service` both declare `EnvironmentFile=/srv/pave/current/.env.production`. The file is loaded by systemd at process start, not by the app. A missing file is a startup failure, not a runtime one.

---

## Secrets

`.env.production` lives on the server as `chmod 600` and is owned by `deploy`. It is not in git. It is not in the release directory. A fresh deploy does not touch it.

If you need to rotate a secret:

1. Edit `.env.production` on the server.
2. `sudo systemctl restart pave-api pave-worker`.
3. The new value is in effect.

`SECRET_KEY` rotation invalidates every existing session cookie, which logs everyone out. That is the intended behaviour; do not rotate it on a whim.
