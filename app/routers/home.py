"""The landing page.

Kept separate from the Phase 5 content router (which serves /{slug} markdown
pages): the index adapts to login state, content pages do not.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.auth.dependencies import get_current_user
from app.models.user import User
from app.services.onboarding import state_for
from app.settings import settings
from app.templating import templates

router = APIRouter(tags=["pages"])


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    user: User | None = Depends(get_current_user),
) -> HTMLResponse:
    # `debug` surfaces the dev-only preview block at the bottom of the
    # template; in production it is False so the markup is not rendered.
    # `onboarding` is None for anonymous visitors and for users who have
    # finished the checklist - the template only renders the banner when
    # there is something for the user to do.
    onboarding = None
    if user is not None:
        state = state_for(user)
        if not state.is_complete:
            onboarding = state
    return templates.TemplateResponse(
        request,
        "index.html",
        {"user": user, "debug": settings.debug, "onboarding": onboarding},
    )


@router.get("/components", response_class=HTMLResponse)
async def components(
    request: Request,
    user: User | None = Depends(get_current_user),
) -> HTMLResponse:
    """The component gallery.

    Renders every shared partial in every variant so designers and AI
    agents can see what is available at a glance. Lives next to the
    landing page because it is informational, not gated.
    """
    return templates.TemplateResponse(
        request, "components.html", {"user": user}
    )
