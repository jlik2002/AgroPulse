"""Выгрузка временного ряда в CSV.

Машинно-читаемый экспорт без каких-либо текстов, сгенерированных языковой
моделью: только наблюдения, расчёты и признаки качества данных. Пользователь
должен иметь возможность продолжить анализ в своих инструментах, не разбирая
чужие формулировки.

Состав колонок задан продуктовым требованием и не должен меняться произвольно —
на него могут опираться внешние обработки.
"""

from __future__ import annotations

import csv
import io
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from agropulse.db.models import Anomaly, Field, Observation

COLUMNS = [
    "field_id",
    "field_name",
    "date",
    "ndvi_mean",
    "ndmi_mean",
    "value_type",
    "valid_fraction",
    "cloud_fraction",
    "source",
    "temperature",
    "precipitation",
    "anomaly_level",
    "risk_score",
    "missing_reason",
]


def _format(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def export_fields(db: Session, fields: list[Field]) -> str:
    """Собрать CSV по перечню полей."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(COLUMNS)

    for field in fields:
        observations = db.scalars(
            select(Observation)
            .where(Observation.field_id == field.id)
            .order_by(Observation.date, Observation.value_type)
        ).all()
        anomalies = db.scalars(
            select(Anomaly).where(Anomaly.field_id == field.id)
        ).all()

        # Уровень аномалии проставляется каждой дате, попавшей в событие:
        # так в выгрузке видно, какие именно точки его образуют.
        level_by_date: dict[object, str] = {}
        for anomaly in anomalies:
            for observation in observations:
                if anomaly.start_date <= observation.date <= anomaly.end_date:
                    level_by_date[observation.date] = anomaly.severity.value

        for observation in observations:
            writer.writerow(
                [
                    field.id,
                    field.name,
                    observation.date.isoformat(),
                    _format(observation.ndvi_mean),
                    _format(observation.ndmi_mean),
                    observation.value_type.value,
                    _format(observation.valid_fraction),
                    _format(observation.cloud_fraction),
                    observation.source,
                    _format(observation.temperature),
                    _format(observation.precipitation),
                    level_by_date.get(observation.date, ""),
                    _format(field.risk_score),
                    observation.missing_reason or "",
                ]
            )

    return buffer.getvalue()


def export_field(db: Session, field_id: uuid.UUID) -> str | None:
    field = db.get(Field, field_id)
    if field is None:
        return None
    return export_fields(db, [field])


def export_project(db: Session, project_id: uuid.UUID) -> str:
    fields = db.scalars(
        select(Field).where(Field.project_id == project_id).order_by(Field.created_at)
    ).all()
    return export_fields(db, fields)
