"""Add exact pipeline chunk contracts and artifact availability.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("job_chunks") as batch:
        batch.add_column(sa.Column("plan_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("input_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("dependency_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("config_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("artifact_schema_version", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("artifact_availability", sa.String(20), nullable=True))
        batch.add_column(sa.Column("artifact_warnings", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("job_chunks") as batch:
        batch.drop_column("artifact_warnings")
        batch.drop_column("artifact_availability")
        batch.drop_column("artifact_schema_version")
        batch.drop_column("config_hash")
        batch.drop_column("dependency_hash")
        batch.drop_column("input_hash")
        batch.drop_column("plan_hash")
