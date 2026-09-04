"""Схемы поля и его временного ряда."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from agropulse.db.models import FieldSource, FieldStatus, ValueType
from agropulse.schemas.geo import PolygonGeometry


class FieldCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    geometry: PolygonGeometry
    # Культура и дата посева необязательны: без них выполняется общий анализ
    # динамики, а культурно-специфичная интерпретация помечается недоступной.
    crop: str | None = Field(default=None, max_length=100)
    sowing_date: date | None = None
    source: FieldSource = FieldSource.DRAWN
    external_ref: str | None = Field(default=None, max_length=100)


class FieldUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    geometry: PolygonGeometry | None = None
    crop: str | None = Field(default=None, max_length=100)
    sowing_date: date | None = None


class FieldRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    geometry: PolygonGeometry
    area_ha: float | None
    crop: str | None
    sowing_date: date | None
    source: FieldSource
    status: FieldStatus
    risk_score: float | None
    created_at: datetime


class ObservationRead(BaseModel):
    """Точка временного ряда.

    `value_type` показывает происхождение значения: наблюдение, восстановление
    или прогноз. Фронтенд обязан различать их визуально — это продуктовый принцип,
    а не деталь оформления.
    """

    model_config = ConfigDict(from_attributes=True)

    date: date
    value_type: ValueType
    source: str
    ndvi_mean: float | None
    ndmi_mean: float | None
    evi_mean: float | None
    valid_fraction: float | None
    cloud_fraction: float | None
    scene_id: str | None
    temperature: float | None
    precipitation: float | None
    ndvi_zscore: float | None
    ndvi_lo: float | None
    ndvi_hi: float | None
    confidence: float | None
    missing_reason: str | None


class TimeseriesRead(BaseModel):
    field_id: uuid.UUID
    field_name: str
    period_from: date
    period_to: date
    observations: list[ObservationRead]
    # Сводка качества данных: пользователь должен видеть, на чём основан вывод.
    stats: dict[str, float | int | None]
