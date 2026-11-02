"""Persist a sanitized typed analysis-job failure code.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("analysis_jobs") as batch:
        batch.add_column(sa.Column("failure_code", sa.String(100), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("analysis_jobs") as batch:
        batch.drop_column("failure_code")
