"""add webhook_events table

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-19

Hand-written to mirror app.models.webhook.WebhookEvent. sa.JSON and
CURRENT_TIMESTAMP keep the DDL portable to the SQLite test database.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_webhook_events_slug"), "webhook_events", ["slug"])


def downgrade() -> None:
    op.drop_index(op.f("ix_webhook_events_slug"), table_name="webhook_events")
    op.drop_table("webhook_events")
