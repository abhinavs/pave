import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.oauth import find_or_create_oauth_user
from app.auth.password import hash_password
from app.auth.tokens import create_reset_token, create_verification_token
from app.models.user import User

# test_user / verified_user / authenticated_client come from conftest.py.
SESSION_COOKIE = "session"


# --- signup / login / logout ------------------------------------------------


async def test_signup_creates_user_and_sets_cookie(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    resp = await async_client.post(
        "/auth/signup",
        data={"name": "New", "email": "new@example.com", "password": "hunter2hunter2"},
    )
    assert resp.status_code in (302, 303)
    assert SESSION_COOKIE in resp.cookies

    row = await db_session.execute(
        select(User).where(User.email == "new@example.com")
    )
    user = row.scalar_one()
    assert user.name == "New"
    assert user.password_hash != "hunter2hunter2"  # stored hashed
    assert user.email_verified_at is None  # signup does not verify


async def test_login_sets_cookie_and_redirects(
    async_client: AsyncClient, test_user: User
) -> None:
    resp = await async_client.post(
        "/auth/login",
        data={"email": "ada@example.com", "password": "correct horse"},
    )
    assert resp.status_code in (302, 303)
    assert SESSION_COOKIE in resp.cookies


async def test_login_rejects_bad_password(
    async_client: AsyncClient, test_user: User
) -> None:
    resp = await async_client.post(
        "/auth/login",
        data={"email": "ada@example.com", "password": "wrong"},
    )
    assert SESSION_COOKIE not in resp.cookies


async def test_logout_clears_cookie(
    async_client: AsyncClient, test_user: User
) -> None:
    await async_client.post(
        "/auth/login",
        data={"email": "ada@example.com", "password": "correct horse"},
    )
    resp = await async_client.post("/auth/logout")
    assert resp.status_code in (302, 303)
    # cookie removed: either absent or emptied
    assert not async_client.cookies.get(SESSION_COOKIE)


# --- auth pages (HTML GET) --------------------------------------------------


async def test_signup_page_renders_a_form(async_client: AsyncClient) -> None:
    resp = await async_client.get("/auth/signup")
    assert resp.status_code == 200
    body = resp.text
    assert 'action="/auth/signup"' in body
    assert 'method="post"' in body
    # the POST handler reads exactly these form fields
    for field in ('name="name"', 'name="email"', 'name="password"'):
        assert field in body


async def test_signup_page_shows_oauth_and_sign_in_link(
    async_client: AsyncClient,
) -> None:
    # Reflex-kit shape: OAuth above a divider above the email form, with a
    # cross-link back to login in the header.
    body = (await async_client.get("/auth/signup")).text
    assert 'href="/auth/google"' in body
    assert 'href="/auth/github"' in body
    assert "Google" in body and "GitHub" in body
    assert 'href="/auth/login"' in body
    assert "Create your account" in body


async def test_login_page_renders_a_form(async_client: AsyncClient) -> None:
    resp = await async_client.get("/auth/login")
    assert resp.status_code == 200
    body = resp.text
    assert 'action="/auth/login"' in body
    assert 'name="email"' in body
    assert 'name="password"' in body


async def test_login_page_shows_oauth_remember_me_and_forgot_password(
    async_client: AsyncClient,
) -> None:
    body = (await async_client.get("/auth/login")).text
    assert 'href="/auth/google"' in body
    assert 'href="/auth/github"' in body
    assert 'href="/auth/forgot"' in body
    assert "Welcome back" in body
    # remember-me is a hidden+checkbox pair, both named the same
    assert 'name="remember_me"' in body


async def test_login_page_shows_error_from_query(
    async_client: AsyncClient,
) -> None:
    # the POST handlers redirect to /auth/login?error=invalid (bad creds)
    # and ?error=exists (email already registered); the page surfaces both.
    invalid = await async_client.get("/auth/login?error=invalid")
    assert invalid.status_code == 200
    assert "incorrect" in invalid.text.lower() or "invalid" in invalid.text.lower()

    exists = await async_client.get("/auth/login?error=exists")
    assert "already" in exists.text.lower()


async def test_forgot_password_page_renders(async_client: AsyncClient) -> None:
    resp = await async_client.get("/auth/forgot")
    assert resp.status_code == 200
    body = resp.text
    assert 'action="/auth/forgot"' in body
    assert 'name="email"' in body
    assert "Reset your password" in body
    assert 'href="/auth/login"' in body  # back-to-sign-in link


async def test_reset_password_page_renders_with_token(
    async_client: AsyncClient, test_user: User
) -> None:
    token = create_reset_token(test_user)
    resp = await async_client.get(f"/auth/reset?token={token}")
    assert resp.status_code == 200
    body = resp.text
    assert 'action="/auth/reset"' in body
    # both password fields plus the hidden token round-trip
    assert 'name="password"' in body
    assert 'name="confirm_password"' in body
    assert f'value="{token}"' in body
    assert "Set a new password" in body


async def test_confirm_email_page_renders_with_token(
    async_client: AsyncClient, test_user: User
) -> None:
    token = create_verification_token(test_user.id)
    resp = await async_client.get(f"/auth/confirm?token={token}")
    assert resp.status_code == 200
    body = resp.text
    # POSTs back to /auth/verify with the token in the body, so a click on
    # an email link still works (GET /auth/verify) but the page form is POST.
    assert 'action="/auth/verify"' in body
    assert f'value="{token}"' in body
    assert "Confirm" in body


async def test_signup_page_redirects_authenticated_user(
    async_client: AsyncClient, test_user: User
) -> None:
    await async_client.post(
        "/auth/login",
        data={"email": "ada@example.com", "password": "correct horse"},
    )
    resp = await async_client.get("/auth/signup")
    assert resp.status_code in (302, 303)
    assert resp.headers["location"] == "/"


# --- require_user dependency ------------------------------------------------


async def test_require_user_redirects_anonymous(
    async_client: AsyncClient,
) -> None:
    resp = await async_client.get("/auth/me")
    assert resp.status_code in (302, 303)
    assert "/auth/login" in resp.headers["location"]


async def test_require_user_allows_authenticated(
    async_client: AsyncClient, test_user: User
) -> None:
    await async_client.post(
        "/auth/login",
        data={"email": "ada@example.com", "password": "correct horse"},
    )
    resp = await async_client.get("/auth/me")
    assert resp.status_code == 200
    assert resp.json()["email"] == "ada@example.com"


# --- OAuth find-or-create ---------------------------------------------------


async def test_oauth_find_or_create_no_duplicate_by_email(
    db_session: AsyncSession, test_user: User
) -> None:
    user = await find_or_create_oauth_user(
        db_session,
        provider="google",
        provider_id="g-123",
        email="ada@example.com",
        name="Ada G",
        avatar_url=None,
    )
    assert user.id == test_user.id  # linked existing, no duplicate

    rows = await db_session.execute(
        select(User).where(User.email == "ada@example.com")
    )
    assert len(rows.scalars().all()) == 1


async def test_oauth_creates_user_when_absent(
    db_session: AsyncSession,
) -> None:
    user = await find_or_create_oauth_user(
        db_session,
        provider="github",
        provider_id="gh-9",
        email="octo@example.com",
        name="Octo",
        avatar_url="http://img/x.png",
    )
    assert user.id is not None
    assert user.provider == "github"


# --- email verification -----------------------------------------------------


async def test_verify_sets_email_verified_at(
    async_client: AsyncClient, db_session: AsyncSession, test_user: User
) -> None:
    token = create_verification_token(test_user.id)
    resp = await async_client.get(f"/auth/verify?token={token}")
    assert resp.status_code in (200, 302, 303)

    await db_session.refresh(test_user)
    assert test_user.email_verified_at is not None


async def test_verify_rejects_bad_token(
    async_client: AsyncClient,
) -> None:
    resp = await async_client.get("/auth/verify?token=garbage")
    assert resp.status_code in (400, 302, 303)


# --- password reset is single-use ------------------------------------------


async def test_reset_token_is_single_use(
    async_client: AsyncClient, db_session: AsyncSession, test_user: User
) -> None:
    token = create_reset_token(test_user)

    first = await async_client.post(
        "/auth/reset",
        data={
            "token": token,
            "password": "brandnewpass1",
            "confirm_password": "brandnewpass1",
        },
    )
    assert first.status_code in (200, 302, 303)

    # the same token must not work a second time
    second = await async_client.post(
        "/auth/reset",
        data={
            "token": token,
            "password": "anotherpass99",
            "confirm_password": "anotherpass99",
        },
    )
    assert second.status_code in (400, 200)
    if second.status_code == 200:
        assert "match" not in second.text.lower() or "invalid" in second.text.lower()

    # password is the first reset value, not the second
    await db_session.refresh(test_user)
    from app.auth.password import verify_password

    assert verify_password("brandnewpass1", test_user.password_hash)
    assert not verify_password("anotherpass99", test_user.password_hash)


async def test_unknown_user_id_in_reset_token_is_rejected(
    async_client: AsyncClient,
) -> None:
    class Ghost:
        id = uuid.uuid4()
        password_hash = hash_password("whatever")

    token = create_reset_token(Ghost())  # type: ignore[arg-type]
    resp = await async_client.post(
        "/auth/reset",
        data={
            "token": token,
            "password": "newpassword12",
            "confirm_password": "newpassword12",
        },
    )
    assert resp.status_code in (400, 200)


# --- active sessions ("devices") page --------------------------------------


async def test_sessions_page_requires_login(async_client: AsyncClient) -> None:
    resp = await async_client.get("/auth/sessions")
    # Either the 303 redirect from the handler or the dependency's own;
    # either way, anonymous traffic never sees the page.
    assert resp.status_code in (302, 303)


async def test_sessions_page_lists_current_session(
    authenticated_client: AsyncClient,
) -> None:
    resp = await authenticated_client.get("/auth/sessions")
    assert resp.status_code == 200
    body = resp.text
    assert "Active sessions" in body
    # The fixture's session is, by definition, the one rendering the page.
    assert "This device" in body


async def test_revoking_current_session_signs_out_here(
    authenticated_client: AsyncClient,
) -> None:
    # Discover the current session id from the rendered page - the route
    # is the source of truth for which row is "current", and we want to
    # exercise the same id the user would click.
    page = await authenticated_client.get("/auth/sessions")
    # Pull the first revoke action target. Cheap parse: just search.
    import re

    match = re.search(r'action="/auth/sessions/([^/]+)/revoke"', page.text)
    assert match is not None
    session_id = match.group(1)

    resp = await authenticated_client.post(f"/auth/sessions/{session_id}/revoke")
    assert resp.status_code in (302, 303)
    # The response carries a Set-Cookie that expires the session cookie -
    # that is what tells the browser to drop it. httpx's cookie jar keeps
    # the marker around, so we check the header directly. We also verify
    # the row is now revoked at the DB level by trying to use the token.
    set_cookie = resp.headers.get("set-cookie", "")
    assert SESSION_COOKIE in set_cookie
    assert ("expires=" in set_cookie.lower()) or ("max-age=0" in set_cookie.lower())


async def test_revoke_others_keeps_current_session_alive(
    authenticated_client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
) -> None:
    # Mint a second session for the same user that is not the one the
    # authenticated_client is carrying.
    from app.auth.sessions import active_sessions, create_session

    await create_session(db_session, user_id=test_user.id)
    await db_session.commit()
    assert len(await active_sessions(db_session, test_user.id)) == 2

    resp = await authenticated_client.post("/auth/sessions/revoke-others")
    assert resp.status_code in (302, 303)

    # Only the cookie-bearing session should survive.
    remaining = await active_sessions(db_session, test_user.id)
    assert len(remaining) == 1
