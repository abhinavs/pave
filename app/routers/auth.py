"""Auth routes: password signup/login, OAuth, verification, reset.

Verification and reset links are delivered through the generic email provider
(see app.email). When the provider is unconfigured, send_email logs the full
message instead of posting it, so the links stay reachable in development and
under tests without any network. Mutating handlers commit explicitly rather
than leaning on get_db, so they behave the same under the test session
override.
"""

import uuid

from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    get_current_session,
    get_current_user,
    require_user,
)
from app.auth.oauth import oauth
from app.auth.password import hash_password, verify_password
from app.auth.sessions import (
    DEFAULT_MAX_AGE,
    SESSION_COOKIE,
    active_sessions,
    create_session,
    revoke_all_for_user,
    revoke_session,
    revoke_session_by_token,
)
from app.auth.tokens import (
    create_reset_token,
    pw_fingerprint,
    verify_reset_token,
    verify_verification_token,
)
from app.database import get_db
from app.email import render_email, send_email
from app.jobs import send_verification_email, soniq
from app.middleware import limiter
from app.models.session import Session
from app.models.user import User
from app.schemas.user import PasswordReset, UserMe
from app.settings import settings
from app.templating import templates

router = APIRouter(prefix="/auth", tags=["auth"])


async def _set_session(
    response: Response, db: AsyncSession, user: User, request: Request
) -> None:
    """Mint a DB-backed session for `user` and attach its opaque token as a
    cookie on `response`. The caller must still commit the surrounding unit
    of work; create_session only flushes."""
    token = await create_session(db, user_id=user.id, request=request)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=DEFAULT_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=not settings.debug,
    )


def _redirect(to: str) -> RedirectResponse:
    return RedirectResponse(to, status_code=status.HTTP_303_SEE_OTHER)


def _absolute(request: Request, path: str) -> str:
    """Build an absolute link from the incoming request's host. Email links
    must be clickable from an inbox, so they cannot be relative."""
    return f"{str(request.base_url).rstrip('/')}{path}"


# --- auth pages (HTML) -----------------------------------------------------
#
# Declared before the OAuth `/{provider}` catch-all below: Starlette matches
# routes in registration order, so without these first `GET /auth/signup`
# would fall through to `/{provider}` and 404 on an unknown provider.

_LOGIN_ERRORS = {
    "invalid": "Incorrect email or password.",
    "exists": "That email is already registered. Log in instead.",
}


@router.get("/signup", response_class=HTMLResponse)
async def signup_page(
    request: Request,
    user: User | None = Depends(get_current_user),
) -> Response:
    if user is not None:
        return _redirect("/")
    return templates.TemplateResponse(request, "auth/signup.html", {"user": None})


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    error: str | None = None,
    user: User | None = Depends(get_current_user),
) -> Response:
    if user is not None:
        return _redirect("/")
    return templates.TemplateResponse(
        request,
        "auth/login.html",
        {"user": None, "error": _LOGIN_ERRORS.get(error or "")},
    )


@router.get("/forgot", response_class=HTMLResponse)
async def forgot_page(request: Request) -> Response:
    """Step 1 of password reset: request a reset link by email."""
    return templates.TemplateResponse(request, "auth/forgot.html", {"user": None})


@router.get("/reset", response_class=HTMLResponse)
async def reset_page(request: Request, token: str) -> Response:
    """Step 2 of password reset: set a new password, with the token round-tripped
    through a hidden input back to POST /auth/reset. The token is validated on
    POST, not here: a stale link should still render the form, so the user gets
    a clear error rather than a 4xx page."""
    return templates.TemplateResponse(
        request, "auth/reset.html", {"user": None, "token": token}
    )


@router.get("/confirm", response_class=HTMLResponse)
async def confirm_page(request: Request, token: str) -> Response:
    """Email confirmation landing. POSTs to /auth/verify with the token in
    the body. The legacy GET /auth/verify?token=... still works for direct
    clicks from an inbox; this page is the click-through alternative."""
    return templates.TemplateResponse(
        request, "auth/confirm.html", {"user": None, "token": token}
    )


# --- password signup / login / logout --------------------------------------


@router.post("/signup")
async def signup(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> Response:
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        return _redirect("/auth/login?error=exists")

    user = User(name=name, email=email, password_hash=hash_password(password))
    db.add(user)
    await db.flush()  # user.id assigned, but the row is not committed yet

    response = _redirect("/")
    await _set_session(response, db, user, request)
    await db.commit()

    # Send the verification email off the request path. The user row is
    # already committed, so the job's idempotent "load by id" lookup is safe.
    await soniq.enqueue(
        send_verification_email,
        user_id=str(user.id),
        verify_base_url=str(request.base_url).rstrip("/"),
    )
    return response


@router.post("/login")
@limiter.limit("5/minute")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> Response:
    row = await db.execute(select(User).where(User.email == email))
    user = row.scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        return _redirect("/auth/login?error=invalid")

    response = _redirect("/")
    await _set_session(response, db, user, request)
    await db.commit()
    return response


@router.post("/logout")
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Revoke this device's session row, then drop the cookie. Other devices
    keep their own sessions - that is the whole point of having rows."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await revoke_session_by_token(db, token)
    response = _redirect("/")
    response.delete_cookie(SESSION_COOKIE)
    return response


@router.get("/me", response_model=UserMe)
async def me(user: User = Depends(require_user)) -> UserMe:
    return UserMe.model_validate(user)


# --- active sessions (devices) ---------------------------------------------
#
# These let a logged-in user see and kill the rows in the sessions table.
# Registered above the OAuth catch-all so /sessions does not look like an
# unknown provider.


@router.get("/sessions", response_class=HTMLResponse)
async def sessions_page(
    request: Request,
    pair: tuple[Session, User] | None = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """List every active session for the current user, marking which row
    issued the cookie on this request."""
    if pair is None:
        return _redirect("/auth/login")
    current_session, user = pair
    sessions = await active_sessions(db, user.id)
    return templates.TemplateResponse(
        request,
        "auth/sessions.html",
        {
            "user": user,
            "sessions": sessions,
            "current_session_id": current_session.id,
        },
    )


@router.post("/sessions/{session_id}/revoke")
async def sessions_revoke(
    session_id: uuid.UUID,
    request: Request,
    pair: tuple[Session, User] | None = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Kill a specific session row. Revoking your own current session is
    fine - the next request just falls back to anonymous; we drop the
    cookie here so the redirect lands on the login page."""
    if pair is None:
        return _redirect("/auth/login")
    current_session, user = pair

    # Only let a user revoke their own rows. We look up via active_sessions
    # rather than trusting the id so a cross-user id collapses to a no-op.
    owned = {s.id for s in await active_sessions(db, user.id)}
    if session_id in owned:
        await revoke_session(db, session_id)

    if session_id == current_session.id:
        response = _redirect("/auth/login?reset=signed-out")
        response.delete_cookie(SESSION_COOKIE)
        return response
    return _redirect("/auth/sessions")


@router.post("/sessions/revoke-others")
async def sessions_revoke_others(
    request: Request,
    pair: tuple[Session, User] | None = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """One-click "sign out everywhere else". Leaves the cookie on this
    request alive, kills everything else owned by this user."""
    if pair is None:
        return _redirect("/auth/login")
    current_session, user = pair
    for s in await active_sessions(db, user.id):
        if s.id != current_session.id:
            await revoke_session(db, s.id)
    return _redirect("/auth/sessions")


# --- email verification ----------------------------------------------------


async def _verify_token(token: str, db: AsyncSession) -> Response:
    user_id = verify_verification_token(token)
    if user_id is None:
        return _redirect("/auth/login?error=verify")

    user = await db.get(User, user_id)
    if user is None:
        return _redirect("/auth/login?error=verify")

    if user.email_verified_at is None:
        from datetime import UTC, datetime

        user.email_verified_at = datetime.now(UTC)
        await db.commit()

    return _redirect("/auth/login?verified=1")


@router.get("/verify")
async def verify(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Direct click from the verification email."""
    return await _verify_token(token, db)


@router.post("/verify")
async def verify_post(
    token: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Confirm-page form post. Same effect as GET; kept separate so the page
    can submit a real form (with CSRF protection downstream) rather than
    relying on a GET side-effect."""
    return await _verify_token(token, db)


@router.get("/verify-needed", response_class=HTMLResponse)
async def verify_needed_page(
    request: Request,
    user: User | None = Depends(get_current_user),
) -> Response:
    """Where the onboarding checklist and require_verified_user both
    send a user whose email is not confirmed yet. Tells them what is
    pending and offers a one-click resend. If they are already verified,
    bounce home - the page is meaningless otherwise."""
    if user is None:
        return _redirect("/auth/login")
    if user.email_verified_at is not None:
        return _redirect("/")
    return templates.TemplateResponse(
        request,
        "auth/verify_needed.html",
        {"user": user, "status": request.query_params.get("status")},
    )


@router.post("/resend")
@limiter.limit("3/minute")
async def resend_verification(
    request: Request,
    user: User | None = Depends(get_current_user),
) -> Response:
    """Re-send the verification email. Rate limited so an account cannot
    be used to spam an inbox. No-op (silently) if the user is already
    verified - we redirect either way so the response shape does not
    leak which case happened."""
    if user is None:
        return _redirect("/auth/login")
    if user.email_verified_at is None:
        await soniq.enqueue(
            send_verification_email,
            user_id=str(user.id),
            verify_base_url=str(request.base_url).rstrip("/"),
        )
    return _redirect("/auth/verify-needed?status=sent")


# --- password reset --------------------------------------------------------


@router.post("/forgot")
@limiter.limit("5/minute")
async def forgot(
    request: Request,
    email: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> Response:
    row = await db.execute(select(User).where(User.email == email))
    user = row.scalar_one_or_none()
    if user is not None and user.password_hash:
        # Send only when the account exists. The redirect below is identical
        # either way, so the response never reveals whether the email matched.
        token = create_reset_token(user)
        reset_url = _absolute(request, f"/auth/reset?token={token}")
        await send_email(
            render_email(
                "password_reset",
                subject="Reset your password",
                to=email,
                reset_url=reset_url,
            )
        )
    return _redirect("/auth/login?reset=requested")


@router.post("/reset")
async def reset(
    token: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> Response:
    # A failed reset returns 400 rather than a redirect: nothing was mutated,
    # and the client (form or API) needs to see the failure, not a 303 to a
    # page that would silently look successful. Phase 3 swaps this for a 200
    # form partial with inline errors.
    try:
        PasswordReset(
            token=token, password=password, confirm_password=confirm_password
        )
    except ValidationError:
        return Response("passwords do not match", status_code=400)

    parsed = verify_reset_token(token)
    if parsed is None:
        return Response("invalid or expired token", status_code=400)
    user_id, fingerprint = parsed

    user = await db.get(User, user_id)
    if user is None:
        return Response("invalid or expired token", status_code=400)

    if pw_fingerprint(user.password_hash) != fingerprint:
        # The fingerprint baked into the token no longer matches: this token
        # was already spent (the reset it authorised changed the hash).
        return Response("token already used", status_code=400)

    user.password_hash = hash_password(password)
    await db.commit()
    # A successful reset has to boot every device, not just the one that
    # initiated the reset - otherwise an attacker who had hijacked a session
    # would still be logged in after the legitimate owner reset the password.
    await revoke_all_for_user(db, user.id)
    return _redirect("/auth/login?reset=done")


# --- OAuth -----------------------------------------------------------------
#
# These use a dynamic {provider} segment, so they are registered last: a
# catch-all path must never be matched ahead of a static one like /verify.


@router.get("/{provider}")
async def oauth_start(provider: str, request: Request) -> Response:
    if provider not in ("google", "github"):
        return Response(status_code=404)
    client = oauth.create_client(provider)
    if client is None:
        return Response(status_code=404)
    redirect_uri = request.url_for("oauth_callback", provider=provider)
    redirect: Response = await client.authorize_redirect(
        request, str(redirect_uri)
    )
    return redirect


@router.get("/{provider}/callback", name="oauth_callback")
async def oauth_callback(
    provider: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    from app.auth.oauth import find_or_create_oauth_user

    client = oauth.create_client(provider)
    if client is None:
        return Response(status_code=404)
    token = await client.authorize_access_token(request)

    if provider == "google":
        info = token.get("userinfo") or await client.userinfo(token=token)
        sub, email = info["sub"], info.get("email")
        name = info.get("name") or email or sub
        avatar = info.get("picture")
    else:
        profile = (await client.get("user", token=token)).json()
        sub = str(profile["id"])
        email = profile.get("email")
        if not email:
            emails = (await client.get("user/emails", token=token)).json()
            primary = next(
                (e for e in emails if e.get("primary") and e.get("verified")),
                None,
            )
            email = primary["email"] if primary else None
        name = profile.get("name") or profile.get("login") or sub
        avatar = profile.get("avatar_url")

    user = await find_or_create_oauth_user(
        db,
        provider=provider,
        provider_id=sub,
        email=email,
        name=name,
        avatar_url=avatar,
    )
    response = _redirect("/")
    await _set_session(response, db, user, request)
    await db.commit()
    return response
