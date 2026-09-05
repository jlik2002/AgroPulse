"""Схемы поля и его временного ряда.

Схемы отделены от ORM-моделей намеренно. Модель `Field` несёт служебные поля —
разложение риска, отчёт о качестве данных, ссылку на внешний объект OSM,
геометрию в формате PostGIS. Отдавать её наружу целиком означало бы, что любое
изменение схемы хранения меняет публичный контракт API.
"""

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agropulse.db.models import FieldSource, FieldStatus, ValueType
from agropulse.schemas.geo import PolygonGeometry

if TYPE_CHECKING:
    from agropulse.db.models import Field as FieldModel
    from agropulse.services.fields import FieldTimeseries


def _clean_crop(value: str) -> str:
    """Привести культуру к виду, пригодному для хранения и сравнения.

    Отдельная функция, а не ограничение длины в поле: `min_length` пропускает
    строку из одних пробелов, а она в отчёте выглядит как указанная культура,
    хотя таковой не является.
    """
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("культура не может быть пустой")
    return cleaned


class FieldCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    geometry: PolygonGeometry
    # Хозяйство обязательно. Решение о поддержке принимается по хозяйству
    # целиком, и поле без владельца не попадает ни в одну строку реестра —
    # то есть просто исчезает из государственного сценария.
    farm_id: uuid.UUID
    # Культура обязательна. Это продуктовое решение, а не техническое:
    # указывается та культура, что растёт на поле в текущем сезоне. Норма
    # строится по прошлым сезонам того же поля, в которых культура могла быть
    # другой, — и без заявленной культуры расхождение с нормой невозможно
    # отличить от севооборота. Она же уходит в сервис моделей и в отчёт.
    crop: str = Field(min_length=1, max_length=100)
    # Дата посева остаётся необязательной: на расчёт фазы она не влияет
    # (см. докстроку `analytics.climatology`), а знают её далеко не всегда.
    sowing_date: date | None = None
    source: FieldSource = FieldSource.DRAWN
    external_ref: str | None = Field(default=None, max_length=100)

    @field_validator("crop")
    @classmethod
    def _validate_crop(cls, value: str) -> str:
        return _clean_crop(value)


class FieldUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    geometry: PolygonGeometry | None = None
    # Смена хозяйства — это перенос поля. `None` значит «не менять»: отвязать
    # поле от хозяйства через API нельзя, раз при создании оно обязательно.
    farm_id: uuid.UUID | None = None
    # `None` здесь значит «не менять», а не «стереть»: очистить культуру
    # нельзя, раз при создании она обязательна.
    crop: str | None = Field(default=None, max_length=100)
    sowing_date: date | None = None

    @field_validator("crop")
    @classmethod
    def _validate_crop(cls, value: str | None) -> str | None:
        return None if value is None else _clean_crop(value)


class ProcessingRequest(BaseModel):
    """Какие поля обрабатывать.

    Пустой список отличается от отсутствующего тела осознанно: `None` значит
    «весь проект», пустой список — что пользователь не выбрал ни одного поля,
    и это ошибка, а не команда обработать всё.
    """

    field_ids: list[uuid.UUID] | None = None


class FieldRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    # В ответе хозяйство необязательно: поля, заведённые до его появления,
    # существуют, и прятать их интерфейс не должен — он показывает их
    # отдельной группой и предлагает перенести.
    farm_id: uuid.UUID | None
    name: str
    geometry: PolygonGeometry
    area_ha: float | None
    # В ответе культура остаётся необязательной: поля, заведённые до того, как
    # она стала обязательной, существуют, и скрывать их интерфейс не должен.
    crop: str | None
    sowing_date: date | None
    source: FieldSource
    # Ссылка на объект в открытом источнике. Нужна интерфейсу, чтобы не
    # предлагать повторно уже добавленный контур после перезагрузки страницы.
    external_ref: str | None
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
            farm_id=field.farm_id,
            name=field.name,
            geometry=PolygonGeometry.model_validate(to_geojson(field.geom)),
            area_ha=field.area_ha,
            crop=field.crop,
            sowing_date=field.sowing_date,
            source=field.source,
            external_ref=field.external_ref,
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
