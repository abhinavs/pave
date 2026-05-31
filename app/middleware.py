"""HTTP middleware: a request id, hardening headers, and CSRF.

CSRF is the double-submit-cookie scheme from starlette-csrf. It is only
installed when not in debug mode: the test and local-dev clients post raw
forms without a token, and gating on debug keeps production protected while
keeping the inner loop friction-free.
"""

import uuid
from collections.abc import Awaitable, Callable

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette_csrf import CSRFMiddleware  # type: ignore[attr-defined]

from app.settings import settings

# Keyed by client IP. Disabled in debug so the test and local clients are not
# throttled while hammering the same endpoint; production (debug=False)
# enforces it. Routes opt in with @limiter.limit(...).
limiter = Limiter(key_func=get_remote_address, enabled=not settings.debug)

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-XSS-Protection": "0",
}


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Tag every request/response with a correlation id for log tracing."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        for header, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response


def install_middleware(app: Starlette) -> None:
    """Attach middleware. Order added is outermost-last, so request id wraps."""
    if not settings.debug:
        app.add_middleware(
            CSRFMiddleware,
            secret=settings.secret_key,
            cookie_name="csrftoken",
            header_name="x-csrftoken",
        )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIDMiddleware)
