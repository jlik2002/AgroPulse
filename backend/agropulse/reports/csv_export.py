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
from datetime import date, timedelta

from agropulse.reports.data import FieldData

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


def export_fields(fields: list[FieldData]) -> str:
    """Собрать CSV по перечню полей."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(COLUMNS)

    for data in fields:
        level_by_date = _anomaly_levels(data)
        for observation in data.observations:
            writer.writerow(
                [
                    data.field.id,
                    data.field.name,
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
                    _format(data.field.risk_score),
                    observation.missing_reason or "",
                ]
            )

    return buffer.getvalue()


def _anomaly_levels(data: FieldData) -> dict[date, str]:
    """Уровень аномалии для каждой даты, попавшей в событие.

    Так в выгрузке видно, какие именно точки образуют аномальный период.
    Проход идёт по датам наблюдений один раз на аномалию, а не вложенным
    циклом по всем наблюдениям для каждой из них.
    """
    levels: dict[date, str] = {}
    for anomaly in data.anomalies:
        day = anomaly.start_date
        while day <= anomaly.end_date:
            levels[day] = anomaly.severity.value
            day += timedelta(days=1)
    return levels


def _format(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)
