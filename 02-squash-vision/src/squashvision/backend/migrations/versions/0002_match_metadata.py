"""Persist optional match upload metadata.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("matches", sa.Column("player_a_name", sa.String(200), nullable=True))
    op.add_column("matches", sa.Column("player_b_name", sa.String(200), nullable=True))
    op.add_column("matches", sa.Column("played_on", sa.Date(), nullable=True))
    op.add_column("matches", sa.Column("score", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("matches", "score")
    op.drop_column("matches", "played_on")
    op.drop_column("matches", "player_b_name")
    op.drop_column("matches", "player_a_name")
