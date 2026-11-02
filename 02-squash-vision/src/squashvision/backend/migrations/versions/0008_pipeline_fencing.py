"""Persist media provenance, checkpoint payloads, and fenced stage publications.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("media_assets") as batch:
        batch.add_column(sa.Column("checksum_sha256", sa.String(64), nullable=True))
        batch.add_column(sa.Column("byte_size", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("duration_us", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("probe_metadata", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("timestamp_index_path", sa.String(500), nullable=True))
        batch.add_column(sa.Column("timestamp_index_sha256", sa.String(64), nullable=True))
    with op.batch_alter_table("job_chunks") as batch:
        batch.add_column(sa.Column("artifact_payload_path", sa.String(500), nullable=True))
        batch.add_column(sa.Column("artifact_payload_size", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("artifact_payload_sha256", sa.String(64), nullable=True))
    op.create_table(
        "stage_publications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(36), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("analysis_job_id", sa.Integer(), sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage", sa.String(14), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("worker_id", sa.String(200), nullable=False),
        sa.Column("claim_token", sa.String(36), nullable=False),
        sa.Column("prediction_revision", sa.Integer(), nullable=True),
        sa.Column("report_revision", sa.Integer(), nullable=True),
        sa.Column("calibration_revision", sa.Integer(), nullable=True),
        sa.UniqueConstraint("analysis_job_id", "stage", "input_hash", name="uq_stage_publication_exact_input"),
    )
    op.create_index("ix_stage_publications_match_id", "stage_publications", ["match_id"])
    op.create_index("ix_stage_publications_analysis_job_id", "stage_publications", ["analysis_job_id"])


def downgrade() -> None:
    op.drop_index("ix_stage_publications_analysis_job_id", table_name="stage_publications")
    op.drop_index("ix_stage_publications_match_id", table_name="stage_publications")
    op.drop_table("stage_publications")
    with op.batch_alter_table("job_chunks") as batch:
        batch.drop_column("artifact_payload_sha256")
        batch.drop_column("artifact_payload_size")
        batch.drop_column("artifact_payload_path")
    with op.batch_alter_table("media_assets") as batch:
        batch.drop_column("timestamp_index_sha256")
        batch.drop_column("timestamp_index_path")
        batch.drop_column("probe_metadata")
        batch.drop_column("duration_us")
        batch.drop_column("byte_size")
        batch.drop_column("checksum_sha256")
