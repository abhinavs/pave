import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WebhookEvent(Base):
    """A received webhook, persisted before any processing.

    `slug` names the integration the event arrived for; `status` tracks the
    job lifecycle. The generic JSON column keeps the raw payload portable to
    the SQLite test database.
    """

    __tablename__ = "webhook_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# == Schema Information
#
# Table name: webhook_events
#
# id         : uuid, primary key, default=uuid4()
# slug       : varchar(128), not null
# status     : varchar(32), not null, default='pending'
# payload    : json, not null, default=dict()
# created_at : timestamp with time zone, not null, server_default=now()
#
# Indexes
#   ix_webhook_events_slug (slug)
#
# == End Schema Information
