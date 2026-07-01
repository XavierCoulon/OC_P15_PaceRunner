"""prediction_runs.calibration_used

Revision ID: c3a9e2b1f0d4
Revises: b2f1a7c4d9e0
Create Date: 2026-06-25 09:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = 'c3a9e2b1f0d4'
down_revision: str | None = 'b2f1a7c4d9e0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'prediction_runs',
        sa.Column('calibration_used', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        op.f('ix_prediction_runs_calibration_used'),
        'prediction_runs',
        ['calibration_used'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_prediction_runs_calibration_used'), table_name='prediction_runs')
    op.drop_column('prediction_runs', 'calibration_used')
