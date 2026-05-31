"""Account: profile page, avatar upload and remove.

The HTTP layer is intentionally thin - parse the file, hand off to
`app.services.avatar`, redirect back to the page. The validation, the
resize, the storage write, and the previous-file eviction all live in
the service so anyone reading this file can see the shape of the routes
without scrolling past Pillow boilerplate."""

from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_user
from app.database import get_db
from app.models.user import User
from app.services.avatar import AvatarError, remove_for_user, replace_for_user
from app.templating import templates

router = APIRouter(prefix="/account", tags=["account"])


@router.get("", response_class=Response)
async def account_page(
    request: Request,
    user: User = Depends(require_user),
) -> Response:
    """The profile page. Reads `?status=` so the upload routes can post-
    redirect-get with a flash message without involving session storage."""
    return templates.TemplateResponse(
        request,
        "account/profile.html",
        {"user": user, "status": request.query_params.get("status")},
    )


@router.post("/avatar")
async def avatar_upload(
    file: UploadFile = File(...),
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    raw = await file.read()
    try:
        await replace_for_user(user, raw)
    except AvatarError as exc:
        # Round-trip the message through the query string. Avatars are a
        # forgiving surface - "too large", "unsupported format" - and the
        # error display lives on the same page.
        return RedirectResponse(
            f"/account?status=error:{exc}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    await db.commit()
    return RedirectResponse(
        "/account?status=avatar-updated",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/avatar/remove")
async def avatar_remove(
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await remove_for_user(user)
    await db.commit()
    return RedirectResponse(
        "/account?status=avatar-removed",
        status_code=status.HTTP_303_SEE_OTHER,
    )
