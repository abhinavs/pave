"""Unit tests for the DB-backed session store.

These exercise the module in isolation - mint, resolve, touch, revoke -
without going through an HTTP request. Cookie wiring and route behaviour
are pinned by the functional auth tests instead."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.sessions import (
    DEFAULT_MAX_AGE,
    active_sessions,
    create_session,
    resolve_session,
    revoke_all_for_user,
    revoke_session,
    revoke_session_by_token,
)
from app.models.session import Session
from app.models.user import User


async def _session_for(db: AsyncSession, token: str) -> Session:
    from app.auth.sessions import _hash_token

    row = await db.execute(
        select(Session).where(Session.token_hash == _hash_token(token))
    )
    return row.scalar_one()


async def test_create_session_returns_token_and_stores_hash(
    db_session: AsyncSession, test_user: User
) -> None:
    token = await create_session(db_session, user_id=test_user.id)
    await db_session.commit()
    # The unhashed token must never be queryable; the row carries the hash.
    rows = await db_session.execute(
        select(Session).where(Session.token_hash == token)
    )
    assert rows.scalar_one_or_none() is None
    row = await _session_for(db_session, token)
    assert row.user_id == test_user.id
    # SQLite returns the stored timestamp naive even when the column is
    # declared with timezone=True; treat it as UTC for the comparison.
    stored = row.expires_at
    if stored.tzinfo is None:
        stored = stored.replace(tzinfo=UTC)
    assert stored > datetime.now(UTC)


async def test_resolve_session_returns_user(
    db_session: AsyncSession, test_user: User
) -> None:
    token = await create_session(db_session, user_id=test_user.id)
    await db_session.commit()
    resolved = await resolve_session(db_session, token)
    assert resolved is not None
    _, user = resolved
    assert user.id == test_user.id


async def test_resolve_session_rejects_unknown_token(
    db_session: AsyncSession,
) -> None:
    assert await resolve_session(db_session, "garbage-token") is None


async def test_resolve_session_rejects_revoked(
    db_session: AsyncSession, test_user: User
) -> None:
    token = await create_session(db_session, user_id=test_user.id)
    await db_session.commit()
    row = await _session_for(db_session, token)
    await revoke_session(db_session, row.id)
    assert await resolve_session(db_session, token) is None


async def test_resolve_session_rejects_expired(
    db_session: AsyncSession, test_user: User
) -> None:
    token = await create_session(db_session, user_id=test_user.id)
    row = await _session_for(db_session, token)
    # Move expiry back without going through revoke - we want the expiry
    # branch to fire, not the revoked-at branch.
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    assert await resolve_session(db_session, token) is None


async def test_revoke_by_token_kills_only_that_session(
    db_session: AsyncSession, test_user: User
) -> None:
    keep = await create_session(db_session, user_id=test_user.id)
    drop = await create_session(db_session, user_id=test_user.id)
    await db_session.commit()
    await revoke_session_by_token(db_session, drop)
    assert await resolve_session(db_session, drop) is None
    assert await resolve_session(db_session, keep) is not None


async def test_revoke_all_kills_every_active_session(
    db_session: AsyncSession, test_user: User
) -> None:
    tokens = [
        await create_session(db_session, user_id=test_user.id) for _ in range(3)
    ]
    await db_session.commit()
    await revoke_all_for_user(db_session, test_user.id)
    for t in tokens:
        assert await resolve_session(db_session, t) is None


async def test_active_sessions_excludes_revoked_and_expired(
    db_session: AsyncSession, test_user: User
) -> None:
    live = await create_session(db_session, user_id=test_user.id)
    killed = await create_session(db_session, user_id=test_user.id)
    aged = await create_session(db_session, user_id=test_user.id)
    await db_session.commit()
    await revoke_session_by_token(db_session, killed)
    aged_row = await _session_for(db_session, aged)
    aged_row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    live_row = await _session_for(db_session, live)
    listed = await active_sessions(db_session, test_user.id)
    assert [s.id for s in listed] == [live_row.id]


@pytest.mark.parametrize("max_age", [DEFAULT_MAX_AGE])
async def test_default_max_age_is_two_weeks(max_age: int) -> None:
    assert max_age == 14 * 24 * 60 * 60
