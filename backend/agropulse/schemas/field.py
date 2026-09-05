"""Схемы поля и его временного ряда.

Схемы отделены от ORM-моделей намеренно. Модель `Field` несёт служебные поля —
разложение риска, отчёт о качестве данных, ссылку на внешний объект OSM,
геометрию в формате PostGIS. Отдавать её наружу целиком означало бы, что любое
изменение схемы хранения меняет публичный контракт API.
"""

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from agropulse.db.models import FieldSource, FieldStatus, ValueType
from agropulse.schemas.geo import PolygonGeometry

if TYPE_CHECKING:
    from agropulse.db.models import Field as FieldModel
    from agropulse.services.fields import FieldTimeseries


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

    @classmethod
    def from_model(cls, field: "FieldModel") -> "FieldRead":
        """Собрать ответ, переведя геометрию из формата PostGIS в GeoJSON.

        Поля перечислены явно, а не собраны обходом колонок таблицы: так
        новая служебная колонка не утечёт в публичный ответ сама собой.
        """
        from agropulse.geometry import to_geojson

        return cls(
            id=field.id,
            project_id=field.project_id,
            name=field.name,
            geometry=PolygonGeometry.model_validate(to_geojson(field.geom)),
            area_ha=field.area_ha,
            crop=field.crop,
            sowing_date=field.sowing_date,
            source=field.source,
            status=field.status,
            risk_score=field.risk_score,
            created_at=field.created_at,
        )


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

    @classmethod
    def from_view(cls, view: "FieldTimeseries") -> "TimeseriesRead":
        return cls(
            field_id=view.field.id,
            field_name=view.field.name,
            period_from=view.period_from,
            period_to=view.period_to,
            observations=[
                ObservationRead.model_validate(observation)
                for observation in view.observations
            ],
            stats=view.stats,
        )
