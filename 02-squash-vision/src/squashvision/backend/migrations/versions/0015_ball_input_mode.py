"""Persist each job's immutable, opt-in ball input photometry.

Revision ID: 0015
Revises: 0014
"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analysis_jobs", sa.Column(
        "ball_input_mode", sa.String(8), nullable=False, server_default="original",
    ))


def downgrade() -> None:
    op.drop_column("analysis_jobs", "ball_input_mode")
