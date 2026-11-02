"""Persist bounded image-space shot contact evidence.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _restore_immutable_triggers() -> None:
    for table in ("rallies", "shots", "corrections"):
        for operation in ("UPDATE", "DELETE"):
            name = f"immutable_{table}_{operation.lower()}"
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {name}"))
            op.execute(
                sa.text(
                    f"CREATE TRIGGER {name} BEFORE {operation} ON {table} "
                    "WHEN EXISTS (SELECT 1 FROM matches WHERE id = OLD.match_id) "
                    f"BEGIN SELECT RAISE(ABORT, 'immutable {table}'); END"
                )
            )


def upgrade() -> None:
    with op.batch_alter_table("rallies") as batch:
        batch.add_column(sa.Column("review_required", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("review_reasons", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("review_status", sa.String(20), nullable=False, server_default="not_required"))
        batch.add_column(sa.Column("evidence_provenance", sa.String(20), nullable=False, server_default="unavailable"))

    with op.batch_alter_table("shots") as batch:
        batch.add_column(sa.Column("contact_x_px", sa.Float(), nullable=True))
        batch.add_column(sa.Column("contact_y_px", sa.Float(), nullable=True))
        batch.add_column(sa.Column("contact_covariance", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("contact_provenance", sa.String(30), nullable=True))
        batch.add_column(sa.Column("contact_source_width", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("contact_source_height", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("review_required", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("classification_payload", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("review_status", sa.String(20), nullable=False, server_default="not_required"))
        batch.add_column(sa.Column("evidence_provenance", sa.String(20), nullable=False, server_default="unavailable"))
    with op.batch_alter_table("corrections") as batch:
        batch.add_column(sa.Column("review_entity_type", sa.String(50), nullable=True))
        batch.add_column(sa.Column("review_entity_id", sa.String(100), nullable=True))
        batch.add_column(sa.Column("review_decision", sa.String(20), nullable=True))
    _restore_immutable_triggers()


def downgrade() -> None:
    with op.batch_alter_table("shots") as batch:
        batch.drop_column("review_status")
        batch.drop_column("evidence_provenance")
        batch.drop_column("classification_payload")
        batch.drop_column("review_required")
        batch.drop_column("contact_source_height")
        batch.drop_column("contact_source_width")
        batch.drop_column("contact_provenance")
        batch.drop_column("contact_covariance")
        batch.drop_column("contact_y_px")
        batch.drop_column("contact_x_px")
    with op.batch_alter_table("corrections") as batch:
        batch.drop_column("review_decision")
        batch.drop_column("review_entity_id")
        batch.drop_column("review_entity_type")
    with op.batch_alter_table("rallies") as batch:
        batch.drop_column("review_reasons")
        batch.drop_column("review_required")
        batch.drop_column("review_status")
        batch.drop_column("evidence_provenance")
    _restore_immutable_triggers()
