"""Persist match deletion intent before filesystem staging.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("matches") as batch:
        batch.add_column(
            sa.Column(
                "deletion_state",
                sa.String(20),
                nullable=False,
                server_default="active",
            )
        )
        batch.add_column(
            sa.Column(
                "deletion_version",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
    with op.batch_alter_table("pending_deletions") as batch:
        batch.add_column(
            sa.Column("match_public_id", sa.String(36), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "deletion_version",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(
            sa.Column(
                "state",
                sa.String(20),
                nullable=False,
                server_default="planned",
            )
        )
        batch.create_index(
            "ix_pending_deletions_match_public_id",
            ["match_public_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("pending_deletions") as batch:
        batch.drop_index("ix_pending_deletions_match_public_id")
        batch.drop_column("state")
        batch.drop_column("deletion_version")
        batch.drop_column("match_public_id")
    with op.batch_alter_table("matches") as batch:
        batch.drop_column("deletion_version")
        batch.drop_column("deletion_state")
