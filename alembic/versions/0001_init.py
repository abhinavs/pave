"""init

Revision ID: 0001
Revises:
Create Date: 2026-05-19

Empty baseline. No models exist yet (Phase 1). Phase 2 adds the users table in
a subsequent revision.
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
