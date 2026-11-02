"""Journal staged artifact deletions for crash-safe cleanup.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pending_deletions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(36), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("original_relative_path", sa.String(500), nullable=False),
        sa.Column("staged_relative_path", sa.String(600), nullable=False, unique=True),
    )


def downgrade() -> None:
    op.drop_table("pending_deletions")
