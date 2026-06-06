from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.sessions import SessionMiddleware

from app.database import engine
from app.errors import install_error_handlers
from app.logging import configure_logging
from app.middleware import install_middleware, limiter
from app.routers import (
    account,
    auth,
    blog,
    dev,
    health,
    home,
    metrics,
    pages,
    webhooks,
)
from app.services.metrics import install_metrics
from app.settings import assert_secret_key_is_production_safe, settings

log = structlog.get_logger()

# Dev-only browser live-reload. arel watches the template, compiled-CSS, and
# content paths and pushes a refresh over a websocket. Python edits are covered
# for free: uvicorn's --reload restarts the worker, the arel client reconnects
# afterwards and reloads the page. Built only under debug so production never
# imports arel (a dev-only dependency) nor exposes the socket.
hot_reload = None
if settings.debug:
    try:
        import arel

        hot_reload = arel.HotReload(
            paths=[
                arel.Path("templates"),
                arel.Path("static/css/app.css"),
                arel.Path("content"),
            ]
        )
    except ImportError:
        # arel ships in requirements-dev only. A production image running with
        # DEBUG=true would not have it; degrade to no live-reload rather than
        # refusing to boot.
        log.warning("arel not installed; live-reload disabled")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging()
    # Fail fast in production rather than serve with a guessable signing key.
    assert_secret_key_is_production_safe(settings)
    log.info("startup", app=settings.app_name, version=settings.app_version)
    async with engine.begin():
        pass  # connection check
    if hot_reload is not None:
        await hot_reload.startup()
    yield
    if hot_reload is not None:
        await hot_reload.shutdown()
    await engine.dispose()
    log.info("shutdown")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/api/docs" if settings.debug else None,
    redoc_url=None,
)

# slowapi needs the limiter on app.state and its handler registered before any
# @limiter.limit route is exercised.
app.state.limiter = limiter
app.add_exception_handler(
    RateLimitExceeded,
    _rate_limit_exceeded_handler,  # type: ignore[arg-type]
)

# SessionMiddleware backs Authlib's OAuth state handshake. install_middleware
# adds request id, security headers, and (outside debug) CSRF on top.
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
install_middleware(app)

# Prometheus middleware: always attached so counters are accumulating, even
# when the scrape endpoint is gated off. Turning the route on later then
# starts surfacing what was already being collected.
install_metrics(app)

install_error_handlers(app)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(health.router)
# Metrics is opt-in: it is an operational endpoint, and shipping it on by
# default would expose internal latency distributions on any clone that
# forgot to firewall /metrics.
if settings.enable_metrics:
    app.include_router(metrics.router)
app.include_router(auth.router)
app.include_router(account.router)
app.include_router(home.router)
app.include_router(webhooks.router)
app.include_router(blog.router)
# Dev preview routes (error pages, etc.) only when DEBUG. Mounted before
# the /{slug} catch-all so /dev/preview/* always wins the match.
if settings.debug:
    app.include_router(dev.router)
# Live-reload socket and the client snippet the layout injects. Same debug
# gate: the route and the `hot_reload` template global only exist locally.
if hot_reload is not None:
    from app.templating import templates

    # arel's HotReload is a full ASGI app, which is wider than the
    # WebSocket-handler signature add_websocket_route is typed for.
    app.add_websocket_route("/hot-reload", route=hot_reload, name="hot-reload")  # type: ignore[arg-type]
    templates.env.globals["hot_reload"] = hot_reload
# pages last: its /{slug} catch-all would otherwise shadow everything above.
app.include_router(pages.router)
