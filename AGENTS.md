# AGENTS.md

Conventions for AI-assisted development in a Pave project. These rules exist
because Pave makes specific architectural choices — async SQLAlchemy, explicit
DTO schemas, Fabric for all task running, vrk for CLI tooling in deploy scripts
— that AI agents will not know to follow unless told explicitly.

Read this file before generating any code, running any command, or proposing
any structural change.

---

## Non-negotiable rules

These are hard stops. If you are about to do any of the following, stop and
flag it to the user instead.

- Never call `sys.exit()`, `os._exit()`, or `os.abort()` in route handlers,
  jobs, or utility functions. These kill the Gunicorn worker process. Raise an
  exception or return an error response.
- Never instantiate an async SQLAlchemy session manually inside a route or job.
  Always use `Depends(get_db)` in routes. Always receive a session as a
  parameter in jobs.
- Never use a sync SQLAlchemy session (`Session`) in an async context. Use
  `AsyncSession` everywhere.
- Never use an ORM model (`app/models/`) as a `response_model` on a route.
  Always use a schema from `app/schemas/`.
- Never use an ORM model as a FastAPI request body type. Always use an input
  schema from `app/schemas/`.
- Never include `password_hash`, `provider_id`, or any internal field in an
  output schema.
- Never run `fab deploy` or any remote Fabric task without first running
  `fab validate`. The validate task exists to catch failures before they reach
  the server.
- Never add a new environment variable without: (1) adding it to `.env.example`
  with a comment, (2) adding it to `.env.schema` as required or optional, (3)
  adding it to `app/settings.py` as a typed field.

---

## Project layout

```
app/models/     SQLAlchemy ORM models only. Nothing else.
app/schemas/    Pydantic schemas (DTOs) only. Nothing else.
app/routers/    FastAPI route handlers.
app/jobs/       Soniq job functions.
app/utils/      Shared utilities. No route logic, no ORM model definitions.
app/auth/       Session management and auth dependencies only.
templates/      Jinja2 HTML templates.
templates/_components/   Reusable HTMX components.
templates/_partials/     HTMX response fragments (not full pages).
content/        Markdown files for blog posts and static pages.
deploy/         Nginx config, systemd unit files, backup scripts.
```

Do not create new top-level directories without explicit instruction. If
unsure where a file belongs, ask.

---

## Database access

The async session is scoped per HTTP request via the `get_db` dependency.

```python
# Correct — route handler
@router.get("/items")
async def list_items(db: AsyncSession = Depends(get_db)) -> list[ItemPublic]:
    result = await db.execute(select(Item))
    return [ItemPublic.model_validate(i) for i in result.scalars()]

# Correct — job function (session passed in, not created)
async def process_payload(event_id: uuid.UUID, db: AsyncSession) -> None:
    event = await db.get(WebhookEvent, event_id)
    ...

# Wrong — never do this
async def some_function():
    async with AsyncSessionLocal() as db:  # creates an unscoped session
        ...
```

Always use `select()` from `sqlalchemy` for queries. Never use the legacy
`Query` API (`db.query(Model)`).

When adding a new ORM model:

1. Define it in `app/models/{name}.py`
2. Import it in `app/models/__init__.py`
3. Run `pave migration --message "add {name} table"`, then review the
   generated migration file before running `pave migrate`
4. Always verify the downgrade step in the migration is correct

---

## Schema (DTO) pattern

Every route boundary has two schemas: one for input, one for output. Both live
in `app/schemas/`. The ORM model never crosses the boundary.

```python
# app/schemas/item.py

class ItemCreate(BaseModel):       # input — what the client sends
    name: str
    description: str | None

class ItemPublic(BaseModel):       # output — what the server returns
    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    model_config = {"from_attributes": True}
```

```python
# app/routers/items.py

@router.post("/items", response_model=ItemPublic, status_code=201)
async def create_item(
    data: ItemCreate,                        # input schema validates the request
    db: AsyncSession = Depends(get_db),
) -> ItemPublic:
    item = Item(name=data.name, description=data.description)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return ItemPublic.model_validate(item)   # output schema controls the response
```

Always set `model_config = {"from_attributes": True}` on output schemas. This
enables `.model_validate(orm_instance)` without manual field mapping.

For paginated responses, use `PaginatedResponse[ItemPublic]` from
`app/schemas/common.py`.

---

## Routes and routers

Create one router file per feature domain: `app/routers/items.py`,
`app/routers/webhooks.py`. Register the router in `app/main.py`.

Route handlers have two surfaces when the route is HTML-facing:

- JSON: `GET /api/items` — returns `ItemPublic` or `list[ItemPublic]`
- HTML: `GET /items` — returns `TemplateResponse`

Prefer the `/api/` prefix for JSON routes when both surfaces coexist. The HTML
route uses `Depends(require_user)` or `Depends(require_verified_user)` for
protected pages.

```python
# HTML route
@router.get("/items")
async def items_page(
    request: Request,
    user: User = Depends(require_verified_user),
    db: AsyncSession = Depends(get_db),
) -> TemplateResponse:
    items = await get_items(db, user_id=user.id)
    return templates.TemplateResponse("items/list.html", {
        "request": request,
        "user": user,
        "items": items,
    })

# HTMX partial — returns a fragment, not a full page
@router.get("/items/search")
async def items_search(
    request: Request,
    q: str = "",
    db: AsyncSession = Depends(get_db),
) -> TemplateResponse:
    items = await search_items(db, q=q)
    return templates.TemplateResponse("items/_partials/table_rows.html", {
        "request": request,
        "items": items,
    })
```

HTMX partial routes live in `templates/_partials/`, not `templates/items/`.

---

## HTMX patterns

**Form submission with inline errors:**
Return `200` with the form partial on validation failure — not `422`. HTMX
treats non-2xx responses as errors and will not swap the content.

```python
@router.post("/items/new")
async def create_item_post(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    try:
        data = ItemCreate(**form)
    except ValidationError as e:
        return templates.TemplateResponse("items/_partials/form.html", {
            "request": request,
            "errors": e.errors(),
            "values": dict(form),
        }, status_code=200)   # 200 so HTMX swaps the content
    ...
```

**Toast notifications:**
Set the `HX-Trigger` response header — do not return a toast in the response
body. The base template listens for the `showToast` event.

```python
from fastapi.responses import HTMLResponse

response = templates.TemplateResponse(...)
response.headers["HX-Trigger"] = json.dumps({
    "showToast": {"message": "Saved.", "type": "success"}
})
return response
```

**Redirects after HTMX mutations:**
Use the `HX-Redirect` response header, not a `302` response. A `302` causes
HTMX to follow the redirect in the background and swap content in place, which
is usually not what you want.

```python
response = Response()
response.headers["HX-Redirect"] = "/items"
return response
```

---

## Soniq jobs

Jobs are defined as async functions in `app/jobs/`. Each job receives
identifiers (IDs), not full ORM objects. It fetches its own data from the
database.

```python
# app/jobs/process_payload.py
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.webhook import WebhookEvent


async def process_payload(event_id: uuid.UUID, db: AsyncSession) -> None:
    event = await db.get(WebhookEvent, event_id)
    if not event:
        return   # job is idempotent — missing record is not an error
    # do work
    event.status = "processed"
    await db.commit()
```

Register the job with Soniq's decorator or registration mechanism — follow
whatever pattern Soniq uses, not a custom one.

Soniq does not inject a database session into jobs (unlike `get_db` for
routes). So `app/jobs/__init__.py` holds a thin `@soniq.job()` adapter that
opens one `AsyncSessionLocal()` per job run and passes it to the pure
`process_payload(event_id, db)` in `app/jobs/process_payload.py`. That single
adapter is the jobs-equivalent of `get_db` and is the _only_ sanctioned place
a session is opened outside a request: do not "fix" it by inlining a session
into the pure job, and do not open a session anywhere else in `app/jobs/`.
The pure job still receives `db` as a parameter and must never create its own.

Enqueue from a route:

```python
await soniq.enqueue(process_payload, event_id=event.id)
```

Never pass full ORM objects to `enqueue()`. They are not serializable. Pass
UUIDs or other primitive identifiers.

---

## Environment variables

Every setting has a home in three places:

| File              | Purpose                                                         |
| ----------------- | --------------------------------------------------------------- |
| `.env.example`    | Documents the variable with a comment and example value         |
| `.env.schema`     | Declares it `required` or `optional:default`                    |
| `app/settings.py` | Typed field on the `Settings` class                             |

If you add a setting to `app/settings.py` without adding it to both
`.env.example` and `.env.schema`, the next developer to clone the project
will get a confusing startup error when Pydantic refuses to load.

```
# .env.schema
DATABASE_URL=required
SECRET_KEY=required
SONIQ_DATABASE_URL=required
ALLOWED_HOSTS=required
EMAIL_API_KEY=optional
EMAIL_API_URL=optional
SENTRY_DSN=optional
WEBHOOQ_ENDPOINT=optional
ENABLE_METRICS=optional:false
DEBUG=optional:false
LOG_LEVEL=optional:info
```

---

## Task runners: pave (local) and fab (remote)

There is no Makefile. Local commands are the `pave` console script
(`app/cli.py`); remote tasks and the deploy gate are Fabric (`fabfile.py`).
The split is deliberate: Typer commands run inside the active venv with no
shell hop, while Fabric earns its keep where SSH `Connection`s and host
targeting actually matter.

```bash
# Local: the pave CLI
pave dev          # uvicorn + tailwind watcher (honcho)
pave test         # pytest
pave lint         # ruff check
pave fmt          # ruff format
pave typecheck    # mypy app/
pave setup        # createdb + migrate + Soniq tables (one-shot)
pave migrate      # alembic upgrade head
pave migration -m "describe the change"   # autogenerate a migration
pave downgrade    # alembic downgrade (defaults to -1)
pave shell        # IPython with app, models, AsyncSessionLocal, soniq
pave worker       # run a Soniq worker
pave soniq-setup  # create Soniq queue tables (idempotent)

# Remote: Fabric
fab validate              # the deploy gate (env, css, migrations, tests, types)
fab staging deploy        # deploy to staging
fab production deploy     # deploy to production (validate runs first)
fab rollback              # flip current back to the previous release
fab logs                  # tail journald for pave-api or pave-worker
fab ssh / fab psql        # interactive shell or psql on the host
fab backup / fab restore  # pg_dump + sha256 verify, and the inverse
fab production setup-tls  # one-shot host hardening (firewall, tls, ...)
```

When adding a new local command, put it in `app/cli.py` as a Typer subcommand
so it runs inside the venv with no shell hop. When adding a remote operation
or anything that needs SSH, add it as a Fabric task in `fabfile.py`. `fab
validate` stays in Fabric because it is the deploy gate that `fab deploy`
will not ship without, but it delegates its local checks to `pave` rather
than duplicating them.

Do not use `subprocess` directly in application code to run CLI tools. Use the
vrk binary only in Fabric tasks and CI workflows, not in route handlers or jobs.

---

## vrk usage

vrk tools used in Pave's deploy pipeline. Deploy-time only — never inside
`app/` Python code.

**`vrk coax` + `vrk grab` + `vrk assert` — health check**

`vrk grab` has no retry flags — that is `vrk coax`. `vrk assert` checks
content, not just status code. Pave's health route returns 200 even when
degraded, so status code alone is not sufficient.

```python
local(
    "vrk coax --times 5 --backoff exp:200ms -- "
    "vrk grab https://yourdomain.com/health | "
    "vrk assert '.status == \"ok\"' --message 'deploy failed health check'"
)
```

Failure after all retries triggers automatic rollback.

**`vrk epoch` — release timestamp**

```python
release_ts = local("vrk epoch --now", hide=True).stdout.strip()
release_name = f"{release_ts}-{short_hash}"
```

**`vrk emit` — optional structured logs**

```bash
git push pave main 2>&1 | vrk emit --tag deploy --parse-level
```

**`vrk mask` — optional, before emit if logs go external**

```bash
git push pave main 2>&1 | vrk mask | vrk emit --tag deploy --parse-level
```

**`vrk digest` — backup integrity in `fab backup`**

```python
local(f"vrk digest --algo sha256 --file {backup_path} --compare")
```

**Posting to Webhooq — httpx, not vrk**

`vrk grab` is GET only. Use httpx directly:

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

---

## Testing

The test suite uses `pytest-asyncio` in auto mode — no `@pytest.mark.asyncio`
decorator needed on test functions.

Standard fixtures from `conftest.py`:

- `async_client` — `httpx.AsyncClient` with the FastAPI app
- `db_session` — async session, rolled back after each test (never committed)
- `test_user` — a created, unverified User
- `verified_user` — a created, email-verified User
- `authenticated_client` — `async_client` with a valid session cookie

Write tests before running `fab validate`. `fab validate` runs the full test
suite as part of its checks. A passing `fab validate` is the deployment gate.

---

## Migrations

```bash
# Generate
pave migration --message "describe what changed"

# Review the generated file in alembic/versions/ before running
# Autogenerate misses: column type changes, check constraints, PostgreSQL-specific types

# Apply locally
pave migrate

# Apply on server (runs automatically in fab deploy, before symlink flip)
# Never run manually on the server
```

Always verify both the upgrade and downgrade steps in a generated migration.
Test the downgrade: `pave downgrade`, check the database, `pave migrate` again.

---

## Content (blog and pages)

Static content lives in `content/` as markdown files with YAML frontmatter.
Do not store blog posts or static pages in the database.

```yaml
---
title: About
published: true
---
Markdown content here.
```

Adding a new page: create `content/pages/{slug}.md`. It is immediately
available at `GET /{slug}` with no code changes required.

Adding a blog post: create `content/blog/YYYY-MM-DD-{slug}.md`. It is
immediately available at `GET /blog/{slug}`.

---

## Design system

Pave ships a design system. Use it. Do not introduce new color values, font
sizes, or spacing values outside of it. Every visual decision should trace back
to a CSS custom property defined in `static/css/source.css`.

**Fonts**

- UI text: Inter (`--font-sans`)
- Display headings (auth h1s, brand wordmark, marketing copy): Newsreader (`--font-serif`, used via the `font-serif` Tailwind utility)
- Code, IDs, timestamps, payloads: IBM Plex Mono (`--font-mono`)
- All three are self-hosted woff2s under `static/fonts/` (Inter and Newsreader as variable axes, Plex Mono as static 400 + 600). Never link Google Fonts at runtime. Never set `font-family` inline.

**Colors — three tiers, one semantic layer**

- Primary (violet) — actions, interactive elements, active states
- Secondary (slate) — supporting structure, secondary actions, borders on
  interactive components
- Tertiary (zinc) — neutral surfaces, backgrounds, dividers, muted text
- Semantic — error (red), warning (amber), success (green), info (blue) —
  status communication only, never decorative

Use CSS custom properties, not raw Tailwind color values:

```html
<!-- Correct -->
<div class="bg-[--bg-surface] border border-[--border-subtle]">
  <!-- Wrong — hardcodes a color outside the token system -->
  <div class="bg-zinc-900 border border-zinc-700"></div>
</div>
```

**Dark mode**
Dark is the default (`<html data-theme="dark">`). Design components in dark
mode first. Light mode is a complete alternate, not an afterthought.

**Buttons — three variants only**

- Primary: `bg-primary-500 text-white hover:bg-primary-600`
- Secondary: `bg-transparent border border-[--border-muted] hover:bg-[--bg-hover]`
- Destructive: `border border-error/30 text-error hover:bg-error/10`
  Never create a fourth button variant. If unsure which to use, it is probably
  Secondary.

**Component conventions**

- Border radius: 4px (sm), 6px (md), 8px (lg). Never `rounded-xl` or larger
  on interactive components.
- Inputs: 32px height, `px-3 py-1.5`, `text-sm`
- No drop shadows in dark mode. Elevation via background lightness and borders.
- Status badges: 10% opacity background fill with matching border. Never solid
  semantic color fills.
- Active nav items: `bg-primary-500/10 text-primary-400 font-medium` — tinted,
  not filled.

**Motion**

- Hover / focus: 100ms
- Component state changes: 150ms
- Panel / toast transitions: 200ms
- No slide, bounce, or spring animations.
- HTMX transitions use `.htmx-swapping` and `.htmx-added` CSS classes defined
  in `source.css`. Never add `transition` inline or via JavaScript.

**Typography**

- Body: `text-sm` (14px) or `text-base` (15px) at `font-weight-normal` (400)
- Labels, metadata: `text-xs` (12px) at `font-weight-medium` (500)
- Headings: `text-xl` to `text-2xl` at `font-weight-semibold` (600)
- Never use `font-bold` (700) in UI — semibold is the ceiling.
- Code / monospace: always IBM Plex Mono at `text-sm`, never smaller.

**Reference implementation**
The webhook demo in `app/routers/webhooks.py` and `templates/webhooks/` is the
canonical example of every component token used in context. When unsure how
something should look, check the demo first.

---

## Code style

- ruff for linting and formatting (`pave lint`, `pave fmt`)
- mypy strict mode on `app/`: all functions must have type annotations
- Sentence-case comments and docstrings, not title case
- No em-dashes in any text: use a comma, a colon, or two sentences instead
- One blank line between logical blocks within a function
- Imports ordered: stdlib, third-party, local (`from app.` last)

Ruff enforces import order automatically. Run `pave fmt` before committing.
