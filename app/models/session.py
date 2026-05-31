"""Server-side session rows.

The cookie value is a random opaque token; only the SHA-256 hash of that
token lives in the database. That means a stolen DB dump cannot be
replayed as a valid cookie, and a stolen cookie can be revoked from any
device the user is logged into.

Why not signed cookies: signed cookies are valid until the secret
rotates or the embedded timestamp expires. They cannot be revoked
individually. With a row per session you can show the user "five active
sessions, here's where each one logged in, kill the laptop one" and
have the next request from that device fall back to anonymous.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# == Schema Information
#
# Table name: sessions
#
# id            : uuid, primary key, default=uuid4()
# user_id       : uuid, not null, foreign key -> users.id
# token_hash    : varchar(64), not null, unique - sha256 hex of cookie
# user_agent    : varchar(255), the agent string at create time
# ip_address    : varchar(45), the address at create time (v6-safe)
# created_at    : timestamp with time zone, not null
# last_used_at  : timestamp with time zone, not null - touched on use
# expires_at    : timestamp with time zone, not null
# revoked_at    : timestamp with time zone, null until explicitly killed
#
# Indexes
#   ix_sessions_token_hash (token_hash) UNIQUE
#   ix_sessions_user_id    (user_id)
#
# == End Schema Information


class Session(Base):
    """One row per active or expired session.

    Resolution is `token cookie -> sha256 hex -> row -> user`. The
    `user_id` index supports the "list my sessions" view; the unique
    `token_hash` index supports the per-request lookup."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    # SHA-256 hex = 64 chars. We store the hash so an attacker with a
    # DB dump cannot forge a cookie - they would need the unhashed
    # token, which never lands on disk on our side.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    user_agent: Mapped[str | None] = mapped_column(String(255), default=None)
    # IPv6 textual form maxes out at 39 chars; 45 gives a little slack
    # for any "::ffff:" v4-mapped prefixes the proxy might add.
    ip_address: Mapped[str | None] = mapped_column(String(45), default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
