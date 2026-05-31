"""Onboarding banner UI wiring.

These pin the contract between the home route, the service, and the
partial: who sees the banner, when it disappears, where the links
point. Copy is not pinned - the template is meant to be rewritten."""

from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

# The partial's marker - stable, not copy. The h2 id would be cleaner
# but the headline is also "Finish setting up your account" and that is
# the kind of string that gets rewritten. So we look for the action
# anchors instead: the /account and /auth/verify-needed hrefs only show
# up when the partial is rendered.


def _banner_present(body: str) -> bool:
    return 'href="/auth/verify-needed"' in body or 'href="/account"' in body


async def test_anonymous_visitor_does_not_see_banner(
    async_client: AsyncClient,
) -> None:
    resp = await async_client.get("/")
    assert resp.status_code == 200
    assert "Finish setting up your account" not in resp.text


async def test_fresh_user_sees_both_steps(
    authenticated_client: AsyncClient, test_user: User
) -> None:
    """`test_user` is unverified and avatar-less, so both rows render."""
    resp = await authenticated_client.get("/")
    assert resp.status_code == 200
    body = resp.text
    assert "Finish setting up your account" in body
    # Both pending steps surface their action targets.
    assert 'href="/auth/verify-needed"' in body
    assert 'href="/account"' in body


async def test_completed_user_does_not_see_banner(
    authenticated_client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
) -> None:
    # Move the user to fully-onboarded directly in the DB - the banner
    # depends on User columns and nothing else.
    test_user.email_verified_at = datetime.now(UTC)
    test_user.avatar_url = "/static/uploads/avatars/x.png"
    db_session.add(test_user)
    await db_session.commit()

    resp = await authenticated_client.get("/")
    assert resp.status_code == 200
    assert "Finish setting up your account" not in resp.text


async def test_verify_needed_page_renders_for_unverified_user(
    authenticated_client: AsyncClient,
) -> None:
    resp = await authenticated_client.get("/auth/verify-needed")
    assert resp.status_code == 200
    body = resp.text
    # The resend form points back at the POST endpoint.
    assert 'action="/auth/resend"' in body


async def test_verify_needed_page_redirects_verified_user(
    authenticated_client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
) -> None:
    test_user.email_verified_at = datetime.now(UTC)
    db_session.add(test_user)
    await db_session.commit()

    resp = await authenticated_client.get("/auth/verify-needed")
    assert resp.status_code in (302, 303)
    assert resp.headers["location"] == "/"


async def test_resend_redirects_with_sent_flash(
    authenticated_client: AsyncClient,
) -> None:
    resp = await authenticated_client.post("/auth/resend")
    assert resp.status_code in (302, 303)
    assert "sent" in resp.headers["location"]


async def test_resend_for_already_verified_user_does_not_claim_sent(
    async_client: AsyncClient, db_session, verified_user
) -> None:
    """A verified user who hits resend should get neutral feedback, not a
    'verification sent' page implying an email went out (it did not)."""
    from app.auth.sessions import SESSION_COOKIE, create_session

    token = await create_session(db_session, user_id=verified_user.id)
    await db_session.commit()
    async_client.cookies.set(SESSION_COOKIE, token)

    resp = await async_client.post("/auth/resend")
    assert resp.status_code in (302, 303)
    assert "sent" not in resp.headers["location"]
