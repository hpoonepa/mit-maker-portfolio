"""Create canonical squash analysis records.

Revision ID: 0001
Revises:
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def record_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    ]


def public_id_constraint() -> sa.UniqueConstraint:
    return sa.UniqueConstraint("public_id")


def upgrade() -> None:
    op.create_table(
        "matches",
        *record_columns(),
        sa.Column("name", sa.String(length=200), nullable=False),
        public_id_constraint(),
    )
    op.create_table(
        "model_assets",
        *record_columns(),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("version", sa.String(length=100), nullable=False),
        sa.Column("relative_path", sa.String(length=500), nullable=False),
        public_id_constraint(),
        sa.UniqueConstraint("model_name", "version"),
        sa.UniqueConstraint("relative_path"),
    )
    op.create_table(
        "media_assets",
        *record_columns(),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "original",
                "proxy",
                "frame",
                "export",
                "model",
                name="media_asset_kind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("relative_path", sa.String(length=500), nullable=False),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        public_id_constraint(),
        sa.UniqueConstraint("relative_path"),
    )
    op.create_index("ix_media_assets_match_id", "media_assets", ["match_id"])
    op.create_table(
        "analysis_jobs",
        *record_columns(),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("source_media_asset_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "succeeded",
                "failed",
                name="analysis_job_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_media_asset_id"], ["media_assets.id"], ondelete="RESTRICT"
        ),
        public_id_constraint(),
    )
    op.create_index("ix_analysis_jobs_match_id", "analysis_jobs", ["match_id"])
    op.create_index(
        "ix_analysis_jobs_source_media_asset_id",
        "analysis_jobs",
        ["source_media_asset_id"],
    )
    op.create_table(
        "job_chunks",
        *record_columns(),
        sa.Column("analysis_job_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "succeeded",
                "failed",
                name="job_chunk_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["analysis_job_id"], ["analysis_jobs.id"], ondelete="CASCADE"
        ),
        public_id_constraint(),
        sa.UniqueConstraint("analysis_job_id", "chunk_index"),
    )
    op.create_index("ix_job_chunks_analysis_job_id", "job_chunks", ["analysis_job_id"])
    op.create_table(
        "calibrations",
        *record_columns(),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("media_asset_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["media_asset_id"], ["media_assets.id"], ondelete="RESTRICT"
        ),
        public_id_constraint(),
    )
    op.create_index("ix_calibrations_match_id", "calibrations", ["match_id"])
    op.create_index(
        "ix_calibrations_media_asset_id", "calibrations", ["media_asset_id"]
    )
    op.create_table(
        "player_tracks",
        *record_columns(),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("analysis_job_id", sa.Integer(), nullable=True),
        sa.Column(
            "slot",
            sa.Enum(
                "near",
                "far",
                name="player_track_slot",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["analysis_job_id"], ["analysis_jobs.id"], ondelete="SET NULL"
        ),
        public_id_constraint(),
    )
    op.create_index("ix_player_tracks_match_id", "player_tracks", ["match_id"])
    op.create_index(
        "ix_player_tracks_analysis_job_id", "player_tracks", ["analysis_job_id"]
    )
    op.create_table(
        "rallies",
        *record_columns(),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("start_frame", sa.Integer(), nullable=False),
        sa.Column("end_frame", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        public_id_constraint(),
        sa.UniqueConstraint("match_id", "ordinal"),
    )
    op.create_index("ix_rallies_match_id", "rallies", ["match_id"])
    op.create_table(
        "shots",
        *record_columns(),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("rally_id", sa.Integer(), nullable=True),
        sa.Column("player_track_id", sa.Integer(), nullable=True),
        sa.Column("frame_index", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "unknown",
                "drive",
                "drop",
                "boast",
                "lob",
                name="shot_kind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rally_id"], ["rallies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["player_track_id"], ["player_tracks.id"], ondelete="SET NULL"
        ),
        public_id_constraint(),
    )
    op.create_index("ix_shots_match_id", "shots", ["match_id"])
    op.create_index("ix_shots_rally_id", "shots", ["rally_id"])
    op.create_index("ix_shots_player_track_id", "shots", ["player_track_id"])
    op.create_table(
        "error_candidates",
        *record_columns(),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("analysis_job_id", sa.Integer(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum(
                "tracking",
                "shot",
                "rally",
                "calibration",
                name="error_candidate_kind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("evidence_version", sa.Integer(), nullable=False),
        sa.Column("evidence_payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["analysis_job_id"], ["analysis_jobs.id"], ondelete="SET NULL"
        ),
        public_id_constraint(),
    )
    op.create_index("ix_error_candidates_match_id", "error_candidates", ["match_id"])
    op.create_index(
        "ix_error_candidates_analysis_job_id",
        "error_candidates",
        ["analysis_job_id"],
    )
    op.create_table(
        "corrections",
        *record_columns(),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("error_candidate_id", sa.Integer(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum(
                "accept",
                "replace",
                "reject",
                name="correction_kind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("replacement_value", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["error_candidate_id"], ["error_candidates.id"], ondelete="SET NULL"
        ),
        public_id_constraint(),
    )
    op.create_index("ix_corrections_match_id", "corrections", ["match_id"])
    op.create_index(
        "ix_corrections_error_candidate_id", "corrections", ["error_candidate_id"]
    )
    op.create_table(
        "report_revisions",
        *record_columns(),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        public_id_constraint(),
        sa.UniqueConstraint("match_id", "revision"),
    )
    op.create_index("ix_report_revisions_match_id", "report_revisions", ["match_id"])


def downgrade() -> None:
    op.drop_table("report_revisions")
    op.drop_table("corrections")
    op.drop_table("error_candidates")
    op.drop_table("shots")
    op.drop_table("rallies")
    op.drop_table("player_tracks")
    op.drop_table("calibrations")
    op.drop_table("job_chunks")
    op.drop_table("analysis_jobs")
    op.drop_table("media_assets")
    op.drop_table("model_assets")
    op.drop_table("matches")
