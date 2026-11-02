"""Add durable model asset state and provenance.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MODEL_STATE = sa.Enum(
    "missing",
    "downloading",
    "ready",
    "corrupt",
    "incompatible",
    name="model_asset_state",
    native_enum=False,
    create_constraint=True,
)


def _record_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.rename_table("model_assets", "model_assets_legacy")
    op.create_table(
        "model_assets",
        *_record_columns(),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("repository", sa.String(length=1000), nullable=False),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("requested_revision", sa.String(length=200), nullable=False),
        sa.Column("resolved_revision", sa.String(length=200), nullable=True),
        sa.Column("etag", sa.String(length=500), nullable=True),
        sa.Column("relative_path", sa.String(length=500), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("declared_license", sa.String(length=100), nullable=False),
        sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("compatibility_version", sa.Integer(), nullable=False),
        sa.Column("state", MODEL_STATE, nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.CheckConstraint(
            "byte_size IS NULL OR byte_size >= 0",
            name="ck_model_assets_nonnegative_byte_size",
        ),
        sa.CheckConstraint(
            "compatibility_version >= 0",
            name="ck_model_assets_compatibility_version",
        ),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("model_name"),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO model_assets (
                id, public_id, created_at, model_name, source, repository,
                filename, requested_revision, resolved_revision, relative_path,
                declared_license, compatibility_version, state, error_code
            )
            SELECT
                id, public_id, created_at, model_name, 'legacy', '',
                relative_path, version, version, relative_path,
                'not-declared', 1, 'corrupt', 'model_provenance_incomplete'
            FROM model_assets_legacy
            """
        )
    )
    op.drop_table("model_assets_legacy")


def downgrade() -> None:
    op.rename_table("model_assets", "model_assets_registry")
    op.create_table(
        "model_assets",
        *_record_columns(),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("version", sa.String(length=100), nullable=False),
        sa.Column("relative_path", sa.String(length=500), nullable=False),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("model_name", "version"),
        sa.UniqueConstraint("relative_path"),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO model_assets (
                id, public_id, created_at, model_name, version, relative_path
            )
            SELECT
                id, public_id, created_at, model_name, requested_revision,
                'models/legacy-' || public_id || '.bin'
            FROM model_assets_registry
            """
        )
    )
    op.drop_table("model_assets_registry")
