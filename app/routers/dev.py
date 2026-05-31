"""Dev-only routes.

Mounted from `app.main` only when `settings.debug` is true. The point is
to let a developer see how the production error pages actually look
without having to coax a real failure out of the app. Two routes:

  GET /dev/preview/404  - returns the templated 404 directly
  GET /dev/preview/500  - raises a RuntimeError so the 500 handler picks
                          it up exactly as it would in production

Keeping these on a separate router (rather than tucking them inside
`home.py`) means production never even sees the import - the router is
not included on the app there - so there is no risk of an opaque debug
endpoint sneaking into a release.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from app.templating import templates

router = APIRouter(prefix="/dev", tags=["dev"])


@router.get("/preview/404", response_class=HTMLResponse)
async def preview_404(request: Request) -> Response:
    """Render the 404 template at a 404 status without raising. Bypasses
    the exception handler entirely, which is useful when iterating on the
    template - a real 404 path would also work but this saves the round
    trip through the handler."""
    return templates.TemplateResponse(
        request,
        "errors/404.html",
        {"user": None, "request_id": getattr(request.state, "request_id", None)},
        status_code=404,
    )


@router.get("/preview/500")
async def preview_500() -> Response:
    """Raise a real exception so the production 500 handler renders. This
    is the path you want for a fair preview - it goes through structlog
    and the request-id chip on the page is the real id for this request."""
    raise RuntimeError(
        "intentional /dev/preview/500 - this is what a real 500 looks like"
    )
