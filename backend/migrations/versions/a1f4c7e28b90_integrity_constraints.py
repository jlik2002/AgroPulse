"""Инварианты на уровне базы и индекс под выборку ряда по типу значения

Ограничения добавляются отдельной ревизией, а не правкой применённой миграции:
initial schema уже накатан на существующие стенды, и переписывать его нельзя.

Каждое ограничение закрепляет правило, которое до сих пор держалось только
Python-кодом. Проверка в Python защищает один путь записи, а данные приходят
ещё и из batch-сценариев и из повторных прогонов задач.

Revision ID: a1f4c7e28b90
Revises: c9bd6d23f610
Create Date: 2026-09-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a1f4c7e28b90"
down_revision: str | None = "c9bd6d23f610"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- один актуальный прогон прогноза на поле ---
    # До ограничения дубли были возможны: прогон удалялся и вставлялся заново,
    # и падение между двумя действиями оставляло лишние строки. Перед созданием
    # уникального индекса такие строки нужно убрать, оставив свежую.
    op.execute(
        """
        DELETE FROM forecast_runs a
        USING forecast_runs b
        WHERE a.field_id = b.field_id
          AND (a.created_at, a.id) < (b.created_at, b.id)
        """
    )
    op.create_unique_constraint("uq_forecast_run_field", "forecast_runs", ["field_id"])

    # --- диапазоны значений ---
    op.create_check_constraint(
        "ck_fields_area_positive", "fields", "area_ha IS NULL OR area_ha > 0"
    )
    op.create_check_constraint(
        "ck_anomalies_duration_positive", "anomalies", "duration_days > 0"
    )
    op.create_check_constraint(
        "ck_jobs_progress_range", "jobs", "progress BETWEEN 0 AND 1"
    )
    op.create_check_constraint(
        "ck_observations_index_range",
        "observations",
        "(ndvi_mean IS NULL OR ndvi_mean BETWEEN -1 AND 1) "
        "AND (ndmi_mean IS NULL OR ndmi_mean BETWEEN -1 AND 1)",
    )
    op.create_check_constraint(
        "ck_observations_fraction_range",
        "observations",
        "(valid_fraction IS NULL OR valid_fraction BETWEEN 0 AND 1) "
        "AND (cloud_fraction IS NULL OR cloud_fraction BETWEEN 0 AND 1)",
    )

    # --- индекс под основную выборку ряда ---
    # Анализ и отчёты читают ряд одного типа значений; без этого индекса база
    # берёт все строки поля и отбрасывает лишние уже после чтения.
    op.create_index(
        "ix_observations_field_type_date",
        "observations",
        ["field_id", "value_type", "date"],
    )


def downgrade() -> None:
    op.drop_index("ix_observations_field_type_date", table_name="observations")
    op.drop_constraint("ck_observations_fraction_range", "observations", type_="check")
    op.drop_constraint("ck_observations_index_range", "observations", type_="check")
    op.drop_constraint("ck_jobs_progress_range", "jobs", type_="check")
    op.drop_constraint("ck_anomalies_duration_positive", "anomalies", type_="check")
    op.drop_constraint("ck_fields_area_positive", "fields", type_="check")
    op.drop_constraint("uq_forecast_run_field", "forecast_runs", type_="unique")
