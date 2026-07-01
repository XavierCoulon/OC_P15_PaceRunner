"""coros_activities + calibration_snapshots

Revision ID: b2f1a7c4d9e0
Revises: 368f458d3213
Create Date: 2026-06-24 17:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects import postgresql

revision: str = 'b2f1a7c4d9e0'
down_revision: str | None = '368f458d3213'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('coros_activities',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('label_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('sport_type', sa.Integer(), nullable=False),
    sa.Column('start_timestamp', sa.Integer(), nullable=False),
    sa.Column('activity_date', sa.Date(), nullable=False),
    sa.Column('distance_km', sa.Float(), nullable=False),
    sa.Column('duration_s', sa.Integer(), nullable=False),
    sa.Column('avg_pace_sec_per_km', sa.Float(), nullable=True),
    sa.Column('avg_hr', sa.Integer(), nullable=True),
    sa.Column('start_lat', sa.Float(), nullable=True),
    sa.Column('start_lon', sa.Float(), nullable=True),
    sa.Column('location', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('elevation_gain_m', sa.Float(), nullable=True),
    sa.Column('streams_fetched', sa.Boolean(), nullable=False),
    sa.Column('weather_temperature_c', sa.Float(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_coros_activities_label_id'), 'coros_activities', ['label_id'], unique=True)
    op.create_index(op.f('ix_coros_activities_start_timestamp'), 'coros_activities', ['start_timestamp'], unique=False)
    op.create_table('calibration_snapshots',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('computed_at', sa.DateTime(), nullable=False),
    sa.Column('sample_count', sa.Integer(), nullable=False),
    sa.Column('profile', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_calibration_snapshots_computed_at'), 'calibration_snapshots', ['computed_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_calibration_snapshots_computed_at'), table_name='calibration_snapshots')
    op.drop_table('calibration_snapshots')
    op.drop_index(op.f('ix_coros_activities_start_timestamp'), table_name='coros_activities')
    op.drop_index(op.f('ix_coros_activities_label_id'), table_name='coros_activities')
    op.drop_table('coros_activities')
