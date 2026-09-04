"""initial schema

Revision ID: c9bd6d23f610
Revises: 
Create Date: 2026-09-04 21:56:03.359144
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'c9bd6d23f610'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Расширение PostGIS нужно до создания колонки geom. Образ postgis/postgis
    # ставит его сам, но миграция не должна на это полагаться: базу могут
    # поднять и на обычном PostgreSQL с установленным пакетом postgis.
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table('projects',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=True),
    sa.Column('period_from', sa.Date(), nullable=False),
    sa.Column('period_to', sa.Date(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('period_to >= period_from', name='ck_projects_period_order'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('raw_cache',
    sa.Column('key', sa.String(length=200), nullable=False),
    sa.Column('provider', sa.String(length=50), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_index(op.f('ix_raw_cache_provider'), 'raw_cache', ['provider'], unique=False)
    op.create_table('fields',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='POLYGON', srid=4326, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.Column('area_ha', sa.Float(), nullable=True),
    sa.Column('crop', sa.String(length=100), nullable=True),
    sa.Column('sowing_date', sa.Date(), nullable=True),
    sa.Column('source', sa.Enum('drawn', 'osm', 'worldcereal', name='field_source', native_enum=False), nullable=False),
    sa.Column('external_ref', sa.String(length=100), nullable=True),
    sa.Column('status', sa.Enum('critical', 'attention', 'normal', 'insufficient_data', 'pending', 'failed', name='field_status', native_enum=False), nullable=False),
    sa.Column('risk_score', sa.Float(), nullable=True),
    sa.Column('risk_breakdown', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('data_quality', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_fields_project_id'), 'fields', ['project_id'], unique=False)
    op.create_index(op.f('ix_fields_status'), 'fields', ['status'], unique=False)
    op.create_table('anomalies',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('field_id', sa.UUID(), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('end_date', sa.Date(), nullable=False),
    sa.Column('duration_days', sa.Integer(), nullable=False),
    sa.Column('severity', sa.Enum('moderate', 'critical', name='anomaly_severity', native_enum=False), nullable=False),
    sa.Column('max_zscore', sa.Float(), nullable=False),
    sa.Column('mean_zscore', sa.Float(), nullable=True),
    sa.Column('restored_fraction', sa.Float(), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('factors', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('explanation', sa.Text(), nullable=True),
    sa.Column('checklist', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('end_date >= start_date', name='ck_anomalies_period_order'),
    sa.ForeignKeyConstraint(['field_id'], ['fields.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_anomalies_field_id'), 'anomalies', ['field_id'], unique=False)
    op.create_table('forecast_runs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('field_id', sa.UUID(), nullable=False),
    sa.Column('horizon_days', sa.Integer(), nullable=False),
    sa.Column('model_version', sa.String(length=100), nullable=True),
    sa.Column('direction', sa.String(length=50), nullable=True),
    sa.Column('risk_level', sa.String(length=50), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('insufficient_reason', sa.String(length=200), nullable=True),
    sa.Column('factors', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['field_id'], ['fields.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_forecast_runs_field_id'), 'forecast_runs', ['field_id'], unique=False)
    op.create_table('jobs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=True),
    sa.Column('field_id', sa.UUID(), nullable=True),
    sa.Column('stage', sa.Enum('search_scenes', 'cloud_masking', 'indices', 'weather', 'timeseries', 'gap_filling', 'anomalies', 'risk_forecast', 'visualization', name='pipeline_stage', native_enum=False), nullable=False),
    sa.Column('status', sa.Enum('queued', 'running', 'done', 'failed', name='job_status', native_enum=False), nullable=False),
    sa.Column('progress', sa.Float(), nullable=False),
    sa.Column('message', sa.Text(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('celery_task_id', sa.String(length=100), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['field_id'], ['fields.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('field_id', 'stage', name='uq_job_field_stage')
    )
    op.create_index(op.f('ix_jobs_field_id'), 'jobs', ['field_id'], unique=False)
    op.create_index(op.f('ix_jobs_project_id'), 'jobs', ['project_id'], unique=False)
    op.create_table('observations',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('field_id', sa.UUID(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('value_type', sa.Enum('observed', 'restored', 'forecast', name='value_type', native_enum=False), nullable=False),
    sa.Column('source', sa.String(length=50), nullable=False),
    sa.Column('ndvi_mean', sa.Float(), nullable=True),
    sa.Column('ndmi_mean', sa.Float(), nullable=True),
    sa.Column('evi_mean', sa.Float(), nullable=True),
    sa.Column('valid_fraction', sa.Float(), nullable=True),
    sa.Column('cloud_fraction', sa.Float(), nullable=True),
    sa.Column('scene_id', sa.String(length=200), nullable=True),
    sa.Column('temperature', sa.Float(), nullable=True),
    sa.Column('precipitation', sa.Float(), nullable=True),
    sa.Column('ndvi_zscore', sa.Float(), nullable=True),
    sa.Column('ndvi_lo', sa.Float(), nullable=True),
    sa.Column('ndvi_hi', sa.Float(), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('missing_reason', sa.String(length=200), nullable=True),
    sa.Column('raw', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.ForeignKeyConstraint(['field_id'], ['fields.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('field_id', 'date', 'value_type', 'source', name='uq_observation_identity')
    )
    op.create_index('ix_observations_field_date', 'observations', ['field_id', 'date'], unique=False)
    op.create_index(op.f('ix_observations_field_id'), 'observations', ['field_id'], unique=False)
    op.create_table('scene_assets',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('field_id', sa.UUID(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('kind', sa.Enum('rgb', 'ndvi', 'ndmi', name='asset_kind', native_enum=False), nullable=False),
    sa.Column('tile_url', sa.Text(), nullable=True),
    sa.Column('thumb_key', sa.String(length=500), nullable=True),
    sa.Column('scene_id', sa.String(length=200), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['field_id'], ['fields.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('field_id', 'date', 'kind', name='uq_scene_asset_identity')
    )
    op.create_index(op.f('ix_scene_assets_field_id'), 'scene_assets', ['field_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_scene_assets_field_id'), table_name='scene_assets')
    op.drop_table('scene_assets')
    op.drop_index(op.f('ix_observations_field_id'), table_name='observations')
    op.drop_index('ix_observations_field_date', table_name='observations')
    op.drop_table('observations')
    op.drop_index(op.f('ix_jobs_project_id'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_field_id'), table_name='jobs')
    op.drop_table('jobs')
    op.drop_index(op.f('ix_forecast_runs_field_id'), table_name='forecast_runs')
    op.drop_table('forecast_runs')
    op.drop_index(op.f('ix_anomalies_field_id'), table_name='anomalies')
    op.drop_table('anomalies')
    op.drop_index(op.f('ix_fields_status'), table_name='fields')
    op.drop_index(op.f('ix_fields_project_id'), table_name='fields')
    op.drop_table('fields')
    op.drop_index(op.f('ix_raw_cache_provider'), table_name='raw_cache')
    op.drop_table('raw_cache')
    op.drop_table('projects')
