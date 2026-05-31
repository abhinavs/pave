"""HTML error pages.

FastAPI's default 404 / 500 are JSON, which is the right call for an API
but wrong for a page the user landed on by clicking a link. These
handlers render `errors/404.html` and `errors/500.html` for HTML callers
and, on the 500 side, log the exception with the request id so the
reference number printed on the page actually means something. JSON
callers (anything under `/api/` or with an Accept that excludes HTML) are
left on JSON so XHRs keep receiving a typed payload."""

import structlog
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.templating import templates

log = structlog.get_logger()


def _wants_html(request: Request) -> bool:
    """The handler renders HTML when the caller looks like a browser.

    /api/ routes are always JSON. Outside that, we trust the Accept
    header: a request that does not say it can take text/html (and does
    say it wants JSON) gets JSON; everything else gets the templated
    page. Most browsers send `*/*` somewhere in their Accept, which
    matches the HTML branch by default."""
    if request.url.path.startswith("/api/"):
        return False
    accept = request.headers.get("accept", "")
    if "application/json" in accept and "text/html" not in accept:
        return False
    return True


def _render_error(
    request: Request, *, template: str, status_code: int
) -> Response:
    """Render an error template with the request id surfaced.

    We deliberately do not look up the current user here: the exception
    may have come from inside that dependency chain, and the error page
    must not itself raise. The header shows the anonymous variant - a
    worse failure mode than missing a name chip would be a blank screen."""
    request_id = getattr(request.state, "request_id", None)
    return templates.TemplateResponse(
        request,
        template,
        {"user": None, "request_id": request_id},
        status_code=status_code,
    )


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> Response:
    """4xx/5xx handler for HTTPException-shaped errors.

    We render the templated 404 page only for 404 specifically: other
    4xx codes (401, 403, 422) carry information a JSON client needs, so
    we keep returning the JSON detail there. Returning HTML for a 401
    from an XHR would mask the real problem at the call site."""
    if exc.status_code == status.HTTP_404_NOT_FOUND and _wants_html(request):
        return _render_error(
            request, template="errors/404.html", status_code=404
        )
    return JSONResponse(
        {"detail": exc.detail}, status_code=exc.status_code,
        headers=getattr(exc, "headers", None),
    )


async def server_error_handler(request: Request, exc: Exception) -> Response:
    """Catch-all for the 500 case. Logs the exception with the request id
    so the reference printed on the page is something operators can grep
    for in the structured log stream."""
    request_id = getattr(request.state, "request_id", None)
    log.exception(
        "unhandled exception",
        path=request.url.path,
        method=request.method,
        request_id=request_id,
    )
    if not _wants_html(request):
        return JSONResponse(
            {"detail": "internal server error", "request_id": request_id},
            status_code=500,
        )
    return _render_error(
        request, template="errors/500.html", status_code=500
    )


def install_error_handlers(app: FastAPI) -> None:
    """Register both handlers. We install the 500 handler in dev too so
    the templated page is reachable from the preview routes; structlog
    still prints the traceback to the terminal, so a developer running
    `pave dev` does not lose the stack trace by gaining the pretty page."""
    # Starlette's stub types `handler` as taking a bare `Exception`. Our
    # 404 handler narrows on StarletteHTTPException at the call site, which
    # is fine at runtime but trips the stub. We mirror the same `type: ignore`
    # pattern app/main.py uses for the slowapi handler.
    app.add_exception_handler(
        StarletteHTTPException,
        http_exception_handler,  # type: ignore[arg-type]
    )
    app.add_exception_handler(Exception, server_error_handler)
