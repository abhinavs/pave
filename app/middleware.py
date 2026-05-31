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
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette_csrf import CSRFMiddleware  # type: ignore[attr-defined]

from app.settings import settings


def _rate_limit_key(request: Request) -> str:
    """Rate-limit per real client IP. Prefer X-Real-IP (set unforgeably by
    nginx) over the spoofable leftmost X-Forwarded-For, so an attacker cannot
    rotate a header to dodge the limit. Falls back to the direct peer."""
    real_ip = request.headers.get("x-real-ip")
    if real_ip and real_ip.strip():
        return real_ip.strip()
    return get_remote_address(request)


# Keyed by client IP. Disabled in debug so the test and local clients are not
# throttled while hammering the same endpoint; production (debug=False)
# enforces it. Routes opt in with @limiter.limit(...).
limiter = Limiter(key_func=_rate_limit_key, enabled=not settings.debug)

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
    # Reject requests with a foreign Host header so ALLOWED_HOSTS is actually
    # enforced. The default ["*"] (dev) means "accept anything", so only wire
    # the filter when a real host list is configured. Added last so it sits
    # outermost and rejects a poisoned Host before anything else runs.
    if settings.allowed_hosts != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
