"""Радарные наблюдения Sentinel-1 и подтверждённость аномалий.

Радар живёт в отдельной таблице, а не в `observations`. Причина физическая:
обратное рассеяние и отражение в оптическом диапазоне — разные величины,
и общий ряд сделал бы бессмысленными и график NDVI, и климатическую норму.
Плюс у Sentinel-1 своя сетка дат, не совпадающая с Sentinel-2.

`anomalies.corroboration` — подтверждённость события независимыми источниками.
Отдельно от существующего `confidence`, потому что это разные вопросы:
`confidence` отвечает «хватило ли данных, чтобы считать», `corroboration` —
«сошлись ли на этом радар, оптика и погода».

Revision ID: d5c81f37a6b2
Revises: b3e7a1d94c25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d5c81f37a6b2"
down_revision: str | None = "b3e7a1d94c25"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "radar_observations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("field_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("orbit_direction", sa.String(length=20), nullable=True),
        sa.Column("relative_orbit", sa.Integer(), nullable=True),
        sa.Column("vv_median_db", sa.Float(), nullable=True),
        sa.Column("vh_median_db", sa.Float(), nullable=True),
        sa.Column("vh_vv_difference_db", sa.Float(), nullable=True),
        sa.Column("rvi_median", sa.Float(), nullable=True),
        sa.Column("spatial_iqr_db", sa.Float(), nullable=True),
        sa.Column("low_signal_fraction", sa.Float(), nullable=True),
        sa.Column("vv_change_db", sa.Float(), nullable=True),
        sa.Column("vh_change_db", sa.Float(), nullable=True),
        sa.Column("rvi_change", sa.Float(), nullable=True),
        sa.Column("change_point_score", sa.Float(), nullable=True),
        sa.Column("valid_fraction", sa.Float(), nullable=True),
        sa.Column("scene_id", sa.String(length=200), nullable=True),
        sa.Column("missing_reason", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["field_id"], ["fields.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "field_id", "date", "source", name="uq_radar_observation_identity"
        ),
        sa.CheckConstraint(
            "(valid_fraction IS NULL OR valid_fraction BETWEEN 0 AND 1) "
            "AND (low_signal_fraction IS NULL OR low_signal_fraction BETWEEN 0 AND 1) "
            "AND (change_point_score IS NULL OR change_point_score BETWEEN 0 AND 1)",
            name="ck_radar_observations_fraction_range",
        ),
        sa.CheckConstraint(
            "orbit_direction IS NULL OR orbit_direction IN ('ascending', 'descending')",
            name="ck_radar_observations_orbit_direction",
        ),
    )
    op.create_index("ix_radar_observations_field_id", "radar_observations", ["field_id"])
    op.create_index(
        "ix_radar_observations_field_date", "radar_observations", ["field_id", "date"]
    )

    op.add_column("anomalies", sa.Column("corroboration", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("anomalies", "corroboration")
    op.drop_index("ix_radar_observations_field_date", table_name="radar_observations")
    op.drop_index("ix_radar_observations_field_id", table_name="radar_observations")
    op.drop_table("radar_observations")
