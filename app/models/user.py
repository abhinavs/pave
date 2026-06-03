import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    """An account. Password-based or OAuth-linked, possibly both.

    `password_hash` and `provider_id` are internal: they never appear in a
    schema under app/schemas/. The generic `Uuid` column type (not the
    PostgreSQL-specific one) keeps the table portable to the SQLite test db.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)

    # Null for users who only ever signed in through an OAuth provider.
    password_hash: Mapped[str | None] = mapped_column(String(255), default=None)

    # "google" / "github" / None. provider_id is the id at that provider.
    provider: Mapped[str | None] = mapped_column(String(32), default=None)
    provider_id: Mapped[str | None] = mapped_column(String(255), default=None)

    avatar_url: Mapped[str | None] = mapped_column(String(512), default=None)

    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    is_active: Mapped[bool] = mapped_column(default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# == Schema Information
#
# Table name: users
#
# id                : uuid, primary key, default=uuid4()
# name              : varchar(255), not null
# email             : varchar(320), not null
# password_hash     : varchar(255)
# provider          : varchar(32)
# provider_id       : varchar(255)
# avatar_url        : varchar(512)
# email_verified_at : timestamp with time zone
# is_active         : boolean, not null, default=True
# created_at        : timestamp with time zone, not null, server_default=now()
# updated_at        : timestamp with time zone, not null, server_default=now()
#
# Indexes
#   ix_users_email (email) UNIQUE
#
# == End Schema Information
