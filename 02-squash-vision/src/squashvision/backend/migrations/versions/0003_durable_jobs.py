"""Add durable analysis queue state and verified chunk checkpoints.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


OLD_JOB_STATUS = sa.Enum(
    "queued",
    "running",
    "succeeded",
    "failed",
    name="analysis_job_status",
    native_enum=False,
    create_constraint=True,
)
JOB_STATUS = sa.Enum(
    "queued",
    "running",
    "paused",
    "completed",
    "failed",
    "cancelled",
    name="analysis_job_status",
    native_enum=False,
    create_constraint=True,
)
REQUESTED_JOB_STATUS = sa.Enum(
    "queued",
    "running",
    "paused",
    "completed",
    "failed",
    "cancelled",
    name="requested_job_status",
    native_enum=False,
    create_constraint=True,
)
OLD_CHUNK_STATUS = sa.Enum(
    "queued",
    "running",
    "succeeded",
    "failed",
    name="job_chunk_status",
    native_enum=False,
    create_constraint=True,
)
CHUNK_STATUS = sa.Enum(
    "pending",
    "running",
    "completed",
    "failed",
    "invalidated",
    name="job_chunk_status",
    native_enum=False,
    create_constraint=True,
)
PROFILE = sa.Enum(
    "fast",
    "balanced",
    "maximum",
    name="processing_profile",
    native_enum=False,
    create_constraint=True,
)
STAGE = sa.Enum(
    "prepare",
    "calibration",
    "players",
    "ball",
    "events",
    "classification",
    "report",
    name="analysis_stage",
    native_enum=False,
    create_constraint=True,
)
CHUNK_STAGE = sa.Enum(
    "prepare",
    "calibration",
    "players",
    "ball",
    "events",
    "classification",
    "report",
    name="job_chunk_stage",
    native_enum=False,
    create_constraint=True,
)


def upgrade() -> None:
    op.execute("PRAGMA ignore_check_constraints = ON")
    op.execute(
        "CREATE TABLE _analysis_job_refs_0003 AS "
        "SELECT 'player_tracks' AS source, id AS row_id, analysis_job_id "
        "FROM player_tracks WHERE analysis_job_id IS NOT NULL "
        "UNION ALL "
        "SELECT 'error_candidates', id, analysis_job_id "
        "FROM error_candidates WHERE analysis_job_id IS NOT NULL"
    )
    op.execute(
        "CREATE TABLE _job_chunks_0003 AS "
        "SELECT id, public_id, created_at, analysis_job_id, chunk_index, "
        "'prepare' AS stage, chunk_index AS start_us, chunk_index + 1 AS end_us, "
        "CASE status WHEN 'queued' THEN 'pending' "
        "WHEN 'succeeded' THEN 'completed' ELSE status END AS status, "
        "NULL AS artifact_path, NULL AS artifact_size, NULL AS artifact_sha256, "
        "created_at AS updated_at FROM job_chunks"
    )
    op.drop_table("job_chunks")
    op.execute("UPDATE analysis_jobs SET status = 'completed' WHERE status = 'succeeded'")
    with op.batch_alter_table("analysis_jobs", recreate="always") as batch_op:
        batch_op.alter_column(
            "status", existing_type=OLD_JOB_STATUS, type_=JOB_STATUS, nullable=False
        )
        batch_op.add_column(
            sa.Column(
                "processing_profile",
                PROFILE,
                nullable=False,
                server_default="balanced",
            )
        )
        batch_op.add_column(
            sa.Column("requested_status", REQUESTED_JOB_STATUS, nullable=True)
        )
        batch_op.add_column(sa.Column("worker_id", sa.String(200), nullable=True))
        batch_op.add_column(sa.Column("claim_token", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("heartbeat_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("current_stage", STAGE, nullable=True))
        batch_op.add_column(sa.Column("error_message", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("version", sa.Integer(), nullable=False, server_default="1")
        )
    op.create_index(
        "uq_analysis_jobs_active_match",
        "analysis_jobs",
        ["match_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('queued', 'running', 'paused')"),
    )
    op.execute(
        "UPDATE player_tracks SET analysis_job_id = "
        "(SELECT analysis_job_id FROM _analysis_job_refs_0003 "
        "WHERE source = 'player_tracks' AND row_id = player_tracks.id) "
        "WHERE id IN (SELECT row_id FROM _analysis_job_refs_0003 "
        "WHERE source = 'player_tracks')"
    )
    op.execute(
        "UPDATE error_candidates SET analysis_job_id = "
        "(SELECT analysis_job_id FROM _analysis_job_refs_0003 "
        "WHERE source = 'error_candidates' AND row_id = error_candidates.id) "
        "WHERE id IN (SELECT row_id FROM _analysis_job_refs_0003 "
        "WHERE source = 'error_candidates')"
    )
    op.create_table(
        "job_chunks",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("public_id", sa.String(36), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "analysis_job_id",
            sa.Integer(),
            sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("stage", CHUNK_STAGE, nullable=False),
        sa.Column("start_us", sa.Integer(), nullable=False),
        sa.Column("end_us", sa.Integer(), nullable=False),
        sa.Column("status", CHUNK_STATUS, nullable=False),
        sa.Column("artifact_path", sa.String(500), nullable=True),
        sa.Column("artifact_size", sa.Integer(), nullable=True),
        sa.Column("artifact_sha256", sa.String(64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "start_us >= 0 AND start_us < end_us", name="valid_job_chunk_range"
        ),
        sa.UniqueConstraint("analysis_job_id", "chunk_index"),
        sa.UniqueConstraint(
            "analysis_job_id",
            "stage",
            "start_us",
            "end_us",
            name="uq_job_chunk_range",
        ),
    )
    op.execute(
        "INSERT INTO job_chunks "
        "(id, public_id, created_at, analysis_job_id, chunk_index, stage, "
        "start_us, end_us, status, artifact_path, artifact_size, artifact_sha256, "
        "updated_at) SELECT id, public_id, created_at, analysis_job_id, "
        "chunk_index, stage, start_us, end_us, status, artifact_path, "
        "artifact_size, artifact_sha256, updated_at FROM _job_chunks_0003"
    )
    op.create_index("ix_job_chunks_analysis_job_id", "job_chunks", ["analysis_job_id"])
    op.drop_table("_job_chunks_0003")
    op.drop_table("_analysis_job_refs_0003")
    op.execute("PRAGMA ignore_check_constraints = OFF")


def downgrade() -> None:
    op.execute("PRAGMA ignore_check_constraints = ON")
    op.execute(
        "CREATE TABLE _analysis_job_refs_0003 AS "
        "SELECT 'player_tracks' AS source, id AS row_id, analysis_job_id "
        "FROM player_tracks WHERE analysis_job_id IS NOT NULL "
        "UNION ALL "
        "SELECT 'error_candidates', id, analysis_job_id "
        "FROM error_candidates WHERE analysis_job_id IS NOT NULL"
    )
    op.execute(
        "CREATE TABLE _job_chunks_0003 AS "
        "SELECT id, public_id, created_at, analysis_job_id, chunk_index, "
        "CASE status WHEN 'pending' THEN 'queued' "
        "WHEN 'completed' THEN 'succeeded' "
        "WHEN 'invalidated' THEN 'failed' ELSE status END AS status "
        "FROM job_chunks"
    )
    op.drop_table("job_chunks")
    op.drop_index("uq_analysis_jobs_active_match", table_name="analysis_jobs")
    op.execute("UPDATE analysis_jobs SET status = 'succeeded' WHERE status = 'completed'")
    op.execute(
        "UPDATE analysis_jobs SET status = 'failed' "
        "WHERE status IN ('paused', 'cancelled')"
    )
    with op.batch_alter_table("analysis_jobs", recreate="always") as batch_op:
        batch_op.alter_column(
            "status", existing_type=JOB_STATUS, type_=OLD_JOB_STATUS, nullable=False
        )
        batch_op.drop_column("version")
        batch_op.drop_column("error_message")
        batch_op.drop_column("current_stage", existing_type=STAGE)
        batch_op.drop_column("heartbeat_at")
        batch_op.drop_column("worker_id")
        batch_op.drop_column("claim_token")
        batch_op.drop_column(
            "requested_status", existing_type=REQUESTED_JOB_STATUS
        )
        batch_op.drop_column("processing_profile", existing_type=PROFILE)
    op.execute(
        "UPDATE player_tracks SET analysis_job_id = "
        "(SELECT analysis_job_id FROM _analysis_job_refs_0003 "
        "WHERE source = 'player_tracks' AND row_id = player_tracks.id) "
        "WHERE id IN (SELECT row_id FROM _analysis_job_refs_0003 "
        "WHERE source = 'player_tracks')"
    )
    op.execute(
        "UPDATE error_candidates SET analysis_job_id = "
        "(SELECT analysis_job_id FROM _analysis_job_refs_0003 "
        "WHERE source = 'error_candidates' AND row_id = error_candidates.id) "
        "WHERE id IN (SELECT row_id FROM _analysis_job_refs_0003 "
        "WHERE source = 'error_candidates')"
    )
    op.create_table(
        "job_chunks",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("public_id", sa.String(36), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "analysis_job_id",
            sa.Integer(),
            sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("status", OLD_CHUNK_STATUS, nullable=False),
        sa.UniqueConstraint("analysis_job_id", "chunk_index"),
    )
    op.execute(
        "INSERT INTO job_chunks "
        "(id, public_id, created_at, analysis_job_id, chunk_index, status) "
        "SELECT id, public_id, created_at, analysis_job_id, chunk_index, status "
        "FROM _job_chunks_0003"
    )
    op.create_index("ix_job_chunks_analysis_job_id", "job_chunks", ["analysis_job_id"])
    op.drop_table("_job_chunks_0003")
    op.drop_table("_analysis_job_refs_0003")
    op.execute("PRAGMA ignore_check_constraints = OFF")
