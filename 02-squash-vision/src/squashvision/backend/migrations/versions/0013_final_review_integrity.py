"""Separate media roles and persist calibrated player/taxonomy integrity.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_MEDIA_KIND = sa.Enum(
    "original", "proxy", "frame", "export", "model",
    name="media_asset_kind", native_enum=False, create_constraint=True,
)
MEDIA_KIND = sa.Enum(
    "original", "proxy", "frame", "timestamp_map", "export", "model",
    name="media_asset_kind", native_enum=False, create_constraint=True,
)
OLD_SHOT_KIND = sa.Enum(
    "unknown", "drive", "drop", "boast", "lob",
    name="shot_kind", native_enum=False, create_constraint=True,
)
SHOT_KIND = sa.Enum(
    "unknown", "serve", "drive", "drop", "boast", "lob", "kill",
    name="shot_kind", native_enum=False, create_constraint=True,
)
SHOT_OUTCOME = sa.Enum(
    "unknown", "in_play", "winner", "error", "stroke", "let",
    name="shot_outcome_kind", native_enum=False, create_constraint=True,
)


def _drop_immutable_triggers() -> None:
    for table in ("player_tracks", "shots"):
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                sa.text(f"DROP TRIGGER IF EXISTS immutable_{table}_{operation.lower()}")
            )


def _restore_immutable_triggers() -> None:
    for table in ("player_tracks", "shots"):
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


def _replace_media_constraint(old: str, new: str) -> None:
    bind = op.get_bind()
    table_sql = bind.exec_driver_sql(
        "SELECT sql FROM sqlite_master "
        "WHERE type = 'table' AND name = 'media_assets'"
    ).scalar_one()
    if table_sql.count(old) != 1:
        raise RuntimeError("media asset constraint shape is not recognized")
    revised_sql = table_sql.replace(old, new)
    schema_version = bind.exec_driver_sql(
        "PRAGMA schema_version"
    ).scalar_one()
    try:
        bind.exec_driver_sql("PRAGMA writable_schema = ON")
        bind.exec_driver_sql(
            "UPDATE sqlite_master SET sql = ? "
            "WHERE type = 'table' AND name = 'media_assets'",
            (revised_sql,),
        )
    finally:
        bind.exec_driver_sql("PRAGMA writable_schema = OFF")
    bind.exec_driver_sql(
        f"PRAGMA schema_version = {int(schema_version) + 1}"
    )


def upgrade() -> None:
    _drop_immutable_triggers()
    op.execute("PRAGMA ignore_check_constraints = ON")
    op.add_column(
        "media_assets",
        sa.Column("timestamp_index_size", sa.Integer(), nullable=True),
    )
    _replace_media_constraint(
        "CONSTRAINT media_asset_kind CHECK "
        "(kind IN ('original', 'proxy', 'frame', 'export', 'model'))",
        "CONSTRAINT media_asset_kind CHECK "
        "(kind IN ('original', 'proxy', 'frame', 'timestamp_map', 'export', 'model'))",
    )
    op.execute(
        "UPDATE media_assets SET kind = 'timestamp_map' "
        "WHERE kind = 'export' AND lower(relative_path) LIKE '%.json'"
    )

    op.execute(
        "UPDATE shots SET outcome = CASE "
        "WHEN outcome IN ('continuation', 'continues') THEN 'in_play' "
        "WHEN outcome IN ('unknown', 'in_play', 'winner', 'error', 'stroke', 'let') "
        "THEN outcome ELSE 'unknown' END"
    )
    with op.batch_alter_table("shots", recreate="always") as batch:
        batch.alter_column(
            "kind", existing_type=OLD_SHOT_KIND, type_=SHOT_KIND, nullable=False
        )
        batch.alter_column(
            "outcome", existing_type=sa.String(50), type_=SHOT_OUTCOME,
            nullable=False, server_default="in_play",
        )

    op.add_column(
        "player_tracks",
        sa.Column("position_covariance", sa.JSON(), nullable=True),
    )
    op.add_column(
        "player_tracks",
        sa.Column("position_uncertainty_m", sa.Float(), nullable=True),
    )
    op.add_column(
        "player_tracks",
        sa.Column(
            "position_provenance",
            sa.String(20),
            nullable=False,
            server_default="unavailable",
        ),
    )
    op.add_column(
        "player_tracks",
        sa.Column("position_unavailable_reason", sa.String(100), nullable=True),
    )
    op.execute("PRAGMA ignore_check_constraints = OFF")
    _restore_immutable_triggers()


def downgrade() -> None:
    raise NotImplementedError(
        "final integrity migration is intentionally forward-only"
    )
