"""Server-side sessions.

The cookie value is an opaque random token. Only its sha256 hash lives in
the `sessions` table, so a database dump cannot be replayed as a valid
cookie - an attacker would need the unhashed token, which never lands on
disk on our side. The lookup chain is `cookie -> sha256 hex -> row -> user`.

Why DB-backed rather than itsdangerous-signed: signed cookies prove
authenticity but cannot be revoked individually. With one row per session
we can list every device a user is logged into, kill a specific one, and
revoke them all on a password reset. That is the user-visible feature this
module exists to enable.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session
from app.models.user import User

# Cookie name and lifetime. Lifetime is also the row's expires_at offset, so
# the cookie and the row die together.
SESSION_COOKIE = "session"
DEFAULT_MAX_AGE = 14 * 24 * 60 * 60  # two weeks, in seconds

# Touching last_used_at on every request would mean a write on every request.
# We only touch when the stored value is older than this, which keeps the
# common read path read-only while still recording recent activity.
_TOUCH_INTERVAL = timedelta(minutes=1)


def _hash_token(token: str) -> str:
    """Sha256 hex of the raw cookie token. 64 chars, matches the column width."""
    return hashlib.sha256(token.encode()).hexdigest()


def _as_utc(value: datetime) -> datetime:
    """Round-trip an "aware" timestamp through SQLite returns it naive, even
    though the column was declared `DateTime(timezone=True)`. Postgres
    preserves the tzinfo. Anywhere we compare a stored value against
    `datetime.now(UTC)` we go through here so the operands always match."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _mint_token() -> str:
    """Opaque, urlsafe, 256 bits of entropy. The bearer is the session."""
    return secrets.token_urlsafe(32)


def _client_ip(request: Request | None) -> str | None:
    """Best-effort client IP.

    Prefer X-Real-IP: Pave's nginx sets it to the actual TCP peer and
    overwrites any client-sent value, so it cannot be forged. The leftmost
    X-Forwarded-For entry is client-supplied and spoofable, so it is only a
    last resort before the direct peer. None outside an HTTP context."""
    if request is None:
        return None
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip() or None
    if request.client:
        return request.client.host
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip() or None
    return None


async def create_session(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    request: Request | None = None,
    max_age: int = DEFAULT_MAX_AGE,
) -> str:
    """Insert a new session row and return the unhashed cookie token.

    The caller is responsible for committing - we add and flush so the row
    has an id, but commit is left to the caller so a signup's "create user
    then create session" sequence can land in one transaction.
    """
    token = _mint_token()
    now = datetime.now(UTC)
    row = Session(
        user_id=user_id,
        token_hash=_hash_token(token),
        user_agent=(request.headers.get("user-agent") if request else None) or None,
        ip_address=_client_ip(request),
        created_at=now,
        last_used_at=now,
        expires_at=now + timedelta(seconds=max_age),
    )
    db.add(row)
    await db.flush()
    return token


async def resolve_session(db: AsyncSession, token: str) -> tuple[Session, User] | None:
    """Return the (session, user) the cookie token vouches for, or None.

    A None answer collapses every failure mode - unknown token, expired,
    revoked, inactive user - into the same outcome the caller treats as
    anonymous. We touch last_used_at if it is stale enough to matter, in
    memory only: the request's own transaction persists it, so a read never
    issues (or can be failed by) its own commit.
    """
    row = await db.execute(
        select(Session).where(Session.token_hash == _hash_token(token))
    )
    session = row.scalar_one_or_none()
    if session is None:
        return None

    now = datetime.now(UTC)
    if session.revoked_at is not None or _as_utc(session.expires_at) <= now:
        return None

    user = await db.get(User, session.user_id)
    if user is None or not user.is_active:
        return None

    # Touch last_used_at when it has drifted past the interval. Set it in
    # memory and let the request's transaction flush it (get_db commits at the
    # end). Committing here would flush unrelated handler work early, and an
    # unguarded commit could turn a plain read into a 500.
    if now - _as_utc(session.last_used_at) >= _TOUCH_INTERVAL:
        session.last_used_at = now

    return session, user


async def revoke_session(db: AsyncSession, session_id: uuid.UUID) -> None:
    """Mark a session revoked. Idempotent - revoking twice is fine."""
    await db.execute(
        update(Session)
        .where(Session.id == session_id, Session.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await db.commit()


async def revoke_session_by_token(db: AsyncSession, token: str) -> None:
    """Revoke whichever session a cookie token currently maps to.

    Used on logout: the route only has the cookie value, not the row id."""
    await db.execute(
        update(Session)
        .where(
            Session.token_hash == _hash_token(token),
            Session.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    await db.commit()


async def revoke_all_for_user(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Kill every active session for a user.

    Called from password reset so a successful reset boots every device,
    not just the one that performed the reset. The fingerprint trick on
    the reset token blocks token replay; this blocks cookie replay.
    """
    await db.execute(
        update(Session)
        .where(Session.user_id == user_id, Session.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await db.commit()


async def active_sessions(db: AsyncSession, user_id: uuid.UUID) -> list[Session]:
    """All non-revoked, non-expired sessions for a user, newest first.

    This is what the "your active sessions" page renders. Expired rows are
    filtered here rather than purged on a schedule - keeping them around
    lets the user see "this session expired on Tuesday" if we ever want to
    show that. The page itself only needs the live ones."""
    now = datetime.now(UTC)
    rows = await db.execute(
        select(Session)
        .where(
            Session.user_id == user_id,
            Session.revoked_at.is_(None),
            Session.expires_at > now,
        )
        .order_by(Session.last_used_at.desc())
    )
    return list(rows.scalars())
