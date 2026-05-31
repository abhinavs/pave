"""Onboarding state projection.

The service is a pure function over the User row, so unit tests just
construct different shapes of User and check what the template would
see. No DB, no transport."""

from datetime import UTC, datetime

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.password import hash_password
from app.models.user import User
from app.services.onboarding import state_for


@pytest_asyncio.fixture
async def fresh_user(db_session: AsyncSession) -> User:
    """A signed-up user with no avatar and no verified email - the
    baseline state every signup starts in."""
    user = User(
        name="Fresh",
        email="fresh@example.com",
        password_hash=hash_password("correct horse"),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def test_fresh_user_has_both_steps_open(fresh_user: User) -> None:
    state = state_for(fresh_user)
    assert not state.is_complete
    assert state.remaining == 2
    assert {s.key for s in state.steps} == {"verify_email", "add_avatar"}
    assert all(s.done is False for s in state.steps)


async def test_verified_user_has_one_step_open(fresh_user: User) -> None:
    fresh_user.email_verified_at = datetime.now(UTC)
    state = state_for(fresh_user)
    assert state.remaining == 1
    verify = next(s for s in state.steps if s.key == "verify_email")
    assert verify.done is True


async def test_avatar_user_has_one_step_open(fresh_user: User) -> None:
    fresh_user.avatar_url = "/static/uploads/avatars/x.png"
    state = state_for(fresh_user)
    assert state.remaining == 1
    avatar = next(s for s in state.steps if s.key == "add_avatar")
    assert avatar.done is True


async def test_fully_onboarded_user_is_complete(fresh_user: User) -> None:
    fresh_user.email_verified_at = datetime.now(UTC)
    fresh_user.avatar_url = "/static/uploads/avatars/x.png"
    state = state_for(fresh_user)
    assert state.is_complete
    assert state.remaining == 0
