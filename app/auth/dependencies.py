"""Auth dependencies.

`get_current_user` is the soft form (None when anonymous, for pages that adapt
to login state). `require_user` is the hard form: it never returns None, it
redirects an anonymous visitor to the login page instead.

Both flow through `resolve_session` so the same DB-backed checks - expiry,
revocation, user-still-active - apply everywhere. There is no signed-cookie
fast path; the cookie is opaque, and the only way to learn what it means is
to look at the sessions table.
"""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.sessions import SESSION_COOKIE, resolve_session
from app.database import get_db
from app.models.session import Session
from app.models.user import User

LOGIN_PATH = "/auth/login"


async def get_current_session(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> tuple[Session, User] | None:
    """The (session, user) pair the cookie resolves to, or None.

    Routes that need the session row itself - "list my devices", "log this
    one out" - use this directly. The thin wrappers below project to just
    the user, which is what most routes want.
    """
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return await resolve_session(db, token)


async def get_current_user(
    pair: tuple[Session, User] | None = Depends(get_current_session),
) -> User | None:
    return pair[1] if pair is not None else None


async def require_user(
    user: User | None = Depends(get_current_user),
) -> User:
    if user is None:
        # 303 so the browser issues a GET to the login page. The body of a
        # redirect is never shown, so a plain HTTPException is fine here.
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="authentication required",
            headers={"Location": LOGIN_PATH},
        )
    return user


async def require_verified_user(
    user: User = Depends(require_user),
) -> User:
    if user.email_verified_at is None:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="email verification required",
            headers={"Location": "/auth/verify-needed"},
        )
    return user
