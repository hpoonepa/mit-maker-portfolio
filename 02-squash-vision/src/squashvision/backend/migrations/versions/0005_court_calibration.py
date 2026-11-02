"""Add versioned court calibration evidence and capabilities.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("calibrations") as batch:
        batch.alter_column(
            "version",
            new_column_name="revision",
            existing_type=sa.Integer(),
            existing_nullable=False,
        )
        batch.add_column(sa.Column("keypoints", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("result", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("confidence", sa.Float(), nullable=True))
        batch.add_column(sa.Column("capabilities", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("frame_width", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("frame_height", sa.Integer(), nullable=True))
    op.execute(
        sa.text(
            """
            UPDATE calibrations
            SET keypoints = '[]',
                result = '{"calibrated": false, "imageToCourt": null, "courtToImage": null, "residualsPx": [], "rmsErrorPx": null, "maxErrorPx": null, "inlierMask": [], "conditionNumber": null, "parameterCovariance": null, "confidence": 0.0, "capabilities": {"imageSpace": true, "floorPosition": false, "movementDistance": false, "speed": false}, "warnings": ["legacy_calibration_incomplete"]}',
                confidence = 0.0,
                capabilities = '{"imageSpace": true, "floorPosition": false, "movementDistance": false, "speed": false}'
            """
        )
    )
    with op.batch_alter_table("calibrations") as batch:
        batch.alter_column("keypoints", existing_type=sa.JSON(), nullable=False)
        batch.alter_column("result", existing_type=sa.JSON(), nullable=False)
        batch.alter_column("confidence", existing_type=sa.Float(), nullable=False)
        batch.alter_column("capabilities", existing_type=sa.JSON(), nullable=False)
        batch.create_unique_constraint(
            "uq_calibrations_match_revision", ["match_id", "revision"]
        )


def downgrade() -> None:
    with op.batch_alter_table("calibrations") as batch:
        batch.drop_constraint("uq_calibrations_match_revision", type_="unique")
        batch.drop_column("frame_height")
        batch.drop_column("frame_width")
        batch.drop_column("capabilities")
        batch.drop_column("confidence")
        batch.drop_column("result")
        batch.drop_column("keypoints")
        batch.alter_column(
            "revision",
            new_column_name="version",
            existing_type=sa.Integer(),
            existing_nullable=False,
        )
