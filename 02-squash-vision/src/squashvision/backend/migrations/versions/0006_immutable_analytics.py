"""Add immutable analytics predictions, corrections, and report revisions.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("player_tracks") as batch:
        batch.add_column(sa.Column("prediction_revision", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("prediction_id", sa.String(100), nullable=True))
        batch.add_column(sa.Column("source_timestamp_us", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("source_evidence_ids", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("x_m", sa.Float(), nullable=True))
        batch.add_column(sa.Column("y_m", sa.Float(), nullable=True))
        batch.add_column(sa.Column("observed", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column("calibration_revision", sa.Integer(), nullable=True))
        batch.create_unique_constraint(
            "uq_player_tracks_prediction", ["match_id", "prediction_revision", "prediction_id"]
        )

    with op.batch_alter_table(
        "rallies",
        naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s_%(column_1_name)s"},
    ) as batch:
        batch.drop_constraint("uq_rallies_match_id_ordinal", type_="unique")
        batch.add_column(sa.Column("prediction_revision", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("prediction_id", sa.String(100), nullable=True))
        batch.add_column(sa.Column("start_timestamp_us", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("end_timestamp_us", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("timing_available", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("source_evidence_ids", sa.JSON(), nullable=False, server_default="[]"))
        batch.create_unique_constraint(
            "uq_rallies_prediction", ["match_id", "prediction_revision", "prediction_id"]
        )
        batch.create_unique_constraint(
            "uq_rallies_revision_ordinal", ["match_id", "prediction_revision", "ordinal"]
        )

    with op.batch_alter_table("shots") as batch:
        batch.add_column(sa.Column("prediction_revision", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("prediction_id", sa.String(100), nullable=True))
        batch.add_column(sa.Column("source_timestamp_us", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("source_evidence_ids", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("hitter", sa.String(10), nullable=True))
        batch.add_column(sa.Column("is_volley", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("outcome", sa.String(50), nullable=False, server_default="in_play"))
        batch.add_column(sa.Column("contact_x_m", sa.Float(), nullable=True))
        batch.add_column(sa.Column("contact_y_m", sa.Float(), nullable=True))
        batch.add_column(sa.Column("speed_m_s", sa.Float(), nullable=True))
        batch.add_column(sa.Column("speed_unavailable_reason", sa.String(100), nullable=True))
        batch.create_unique_constraint(
            "uq_shots_prediction", ["match_id", "prediction_revision", "prediction_id"]
        )

    with op.batch_alter_table("error_candidates") as batch:
        batch.add_column(sa.Column("prediction_revision", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("prediction_id", sa.String(100), nullable=True))
        batch.add_column(sa.Column("target_type", sa.String(50), nullable=True))
        batch.add_column(sa.Column("target_prediction_id", sa.String(100), nullable=True))
        batch.add_column(sa.Column("source_timestamp_us", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("source_evidence_ids", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("review_status", sa.String(20), nullable=False, server_default="pending"))
        batch.create_unique_constraint(
            "uq_error_candidates_prediction", ["match_id", "prediction_revision", "prediction_id"]
        )

    for table in ("player_tracks", "rallies", "shots", "error_candidates"):
        op.execute(
            sa.text(
                f"UPDATE {table} SET prediction_id = public_id "
                "WHERE prediction_id IS NULL"
            )
        )
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                "prediction_id",
                existing_type=sa.String(100),
                nullable=False,
            )
    op.execute(
        sa.text(
            "UPDATE error_candidates "
            "SET target_type = 'unknown', target_prediction_id = public_id "
            "WHERE target_type IS NULL OR target_prediction_id IS NULL"
        )
    )
    with op.batch_alter_table("error_candidates") as batch:
        batch.alter_column(
            "target_type", existing_type=sa.String(50), nullable=False
        )
        batch.alter_column(
            "target_prediction_id", existing_type=sa.String(100), nullable=False
        )

    with op.batch_alter_table("corrections") as batch:
        batch.add_column(sa.Column("supersedes_correction_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("command_type", sa.String(50), nullable=False, server_default="accept"))
        batch.add_column(sa.Column("target_type", sa.String(50), nullable=False, server_default="error_candidate"))
        batch.add_column(sa.Column("target_id", sa.String(100), nullable=False, server_default="legacy"))
        batch.add_column(sa.Column("prediction_revision", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("expected_report_revision", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("before_payload", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("after_payload", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("reason", sa.Text(), nullable=False, server_default="legacy correction"))
        batch.add_column(sa.Column("source_timestamp_us", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("source_evidence_ids", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("status", sa.String(20), nullable=False, server_default="active"))
        batch.add_column(sa.Column("conflict_details", sa.JSON(), nullable=True))

    op.execute(
        sa.text(
            "UPDATE corrections SET "
            "command_type = CASE kind WHEN 'accept' THEN 'accept' WHEN 'reject' THEN 'reject' ELSE 'legacy_replace' END, "
            "target_type = 'error_candidate', "
            "target_id = COALESCE((SELECT public_id FROM error_candidates WHERE id = corrections.error_candidate_id), 'legacy:' || public_id), "
            "before_payload = json_object('legacy_kind', kind, 'legacy_replacement_value', replacement_value), "
            "after_payload = json_object('legacy_kind', kind, 'legacy_replacement_value', replacement_value), "
            "reason = 'migrated legacy correction', "
            "status = CASE WHEN kind IN ('accept', 'reject') THEN 'active' ELSE 'conflict' END, "
            "conflict_details = CASE WHEN kind IN ('accept', 'reject') THEN NULL "
            "ELSE json_object('reason', 'legacy_unmappable', 'candidate_ids', json('[]')) END"
        )
    )
    with op.batch_alter_table("corrections") as batch:
        batch.drop_constraint("correction_kind", type_="check")
        batch.drop_column("kind")
        batch.drop_column("replacement_value")
        batch.create_check_constraint(
            "correction_status",
            "status IN ('active', 'conflict', 'superseded')",
        )
        batch.create_foreign_key(
            "fk_corrections_supersedes", "corrections", ["supersedes_correction_id"], ["id"], ondelete="RESTRICT"
        )
        batch.create_index("ix_corrections_supersedes_correction_id", ["supersedes_correction_id"])

    with op.batch_alter_table("report_revisions") as batch:
        batch.add_column(sa.Column("correction_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("prediction_revision", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("calibration_revision", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("sections", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("section_hashes", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("dependency_hashes", sa.JSON(), nullable=False, server_default="{}"))
        batch.create_foreign_key(
            "fk_report_revisions_correction", "corrections", ["correction_id"], ["id"], ondelete="RESTRICT"
        )
        batch.create_index("ix_report_revisions_correction_id", ["correction_id"])

    legacy_sections = {
        name: {
            "availability": {
                "available": False,
                "reason": "legacy_schema_incompatible",
            },
            "_evidence_ids": [],
        }
        for name in (
            "overview",
            "shots",
            "rallies",
            "movement",
            "errors",
            "trajectory",
            "head_to_head",
            "coaching",
            "review",
        )
    }
    report_table = sa.table(
        "report_revisions",
        sa.column("schema_version", sa.Integer()),
        sa.column("sections", sa.JSON()),
        sa.column("section_hashes", sa.JSON()),
        sa.column("dependency_hashes", sa.JSON()),
    )
    legacy_hashes = {
        name: "legacy_schema_incompatible" for name in legacy_sections
    }
    op.get_bind().execute(
        report_table.update().values(
            schema_version=0,
            sections=legacy_sections,
            section_hashes=legacy_hashes,
            dependency_hashes=legacy_hashes,
        )
    )

    for table in (
        "player_tracks",
        "rallies",
        "shots",
        "error_candidates",
        "corrections",
        "report_revisions",
    ):
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER immutable_{table}_{operation.lower()} "
                    f"BEFORE {operation} ON {table} "
                    "WHEN EXISTS (SELECT 1 FROM matches WHERE id = OLD.match_id) "
                    f"BEGIN SELECT RAISE(ABORT, 'immutable {table}'); END"
                )
            )


def downgrade() -> None:
    raise NotImplementedError("immutable analytics migration is intentionally forward-only")
