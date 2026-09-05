"""Схемы результатов анализа: аномалии, риск, сводка по проекту."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from agropulse.db.models import AnomalySeverity, FieldStatus


class AnomalyRead(BaseModel):
    """Негативный аномальный период."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    start_date: date
    end_date: date
    duration_days: int
    severity: AnomalySeverity
    max_zscore: float
    mean_zscore: float | None
    # Доля восстановленных точек внутри периода: чем выше, тем осторожнее вывод.
    restored_fraction: float | None
    # Можно ли верить событию: confirmed | unverified | disputed.
    # Основания вердикта лежат в `factors["trust"]`: без них это ещё один
    # непонятный ярлык, а не сигнал.
    trust: str | None
    # Совпавшие факторы и гипотезы о причинах. Это версии, а не диагноз.
    factors: dict | None
    explanation: str | None


class RadarPoint(BaseModel):
    """Точка радарного ряда Sentinel-1."""

    model_config = ConfigDict(from_attributes=True)

    date: date
    # Геометрия съёмки: сравнивать между собой можно только точки одной орбиты.
    orbit_direction: str | None
    relative_orbit: int | None
    vv_median_db: float | None
    vh_median_db: float | None
    vh_vv_difference_db: float | None
    rvi_median: float | None
    spatial_iqr_db: float | None
    low_signal_fraction: float | None
    vv_change_db: float | None
    vh_change_db: float | None
    rvi_change: float | None
    change_point_score: float | None
    valid_fraction: float | None
    missing_reason: str | None


class RadarEventRead(BaseModel):
    """Резкое изменение радарного сигнала.

    Причина не называется: одно и то же изменение возможно по нескольким
    причинам, и выбрать между ними радар не может.
    """

    date: date
    kind: str
    magnitude_db: float
    score: float | None
    title: str
    hypotheses: list[str]
    # Удержался ли новый уровень на следующей съёмке той же орбиты. У последнего
    # снимка ряда проверить нечем, и такое событие показывается с оговоркой.
    confirmed: bool


class RadarSeries(BaseModel):
    """Радарный ряд поля вместе с найденными в нём событиями."""

    field_id: uuid.UUID
    source: str | None
    points: list[RadarPoint]
    events: list[RadarEventRead]


class RiskRead(BaseModel):
    """Составной риск с раскрытием вклада факторов."""

    model_config = ConfigDict(from_attributes=True)

    field_id: uuid.UUID
    status: FieldStatus
    score: float | None
    breakdown: dict | None
    explanation: list[str]
    confidence: float | None
    insufficient_reason: str | None
    climatology: dict | None


class ForecastRead(BaseModel):
    """Метаданные прогноза. Сами точки ряда приходят вместе с временным рядом.

    Отдаётся отдельно от `RiskRead`: риск описывает текущее состояние поля,
    а прогноз — будущее, и на экране это разные блоки с разной осторожностью
    формулировок.
    """

    # protected_namespaces отключён осознанно: поле называется `model_version`,
    # потому что так его называет контракт с сервисом моделей, а pydantic
    # по умолчанию считает префикс `model_` своим и предупреждает об этом.
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    field_id: uuid.UUID
    horizon_days: int
    model_version: str | None
    # declining / improving / stable
    direction: str | None
    # high / moderate / low
    risk_level: str | None
    confidence: float | None
    # Заполняется, когда данных не хватило: интерфейс обязан сказать об этом прямо.
    insufficient_reason: str | None
    factors: dict | None
    created_at: datetime | None


class FieldSummary(BaseModel):
    """Строка сводного дашборда."""

    model_config = ConfigDict(from_attributes=True)

    field_id: uuid.UUID
    name: str
    area_ha: float | None
    crop: str | None
    status: FieldStatus
    risk_score: float | None
    anomalies_count: int
    worst_anomaly: AnomalyRead | None
    observed_points: int
    restored_points: int
    mean_valid_fraction: float | None
    # Место в очереди на осмотр. У полей без данных приоритета нет.
    inspection_rank: int | None


class ProjectSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: uuid.UUID
    period_from: date
    period_to: date
    total_fields: int
    critical: int
    attention: int
    normal: int
    insufficient_data: int
    fields: list[FieldSummary]
