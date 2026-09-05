"""Интерфейс к сервису ML-моделей.

Модели восстановления пропусков и прогноза живут в отдельном сервисе, который
разрабатывается независимо. Здесь описан только контракт; конкретный транспорт
скрыт за реализацией, поэтому переход с REST на брокер сообщений не затронет
пайплайн. Контракт зафиксирован в `docs/ML_API.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date
from typing import Protocol, runtime_checkable


@dataclass(slots=True)
class SeriesPoint:
    date: date
    primary_ndvi: float | None
    features: dict[str, float | None] = dataclass_field(default_factory=dict)


@dataclass(slots=True)
class ImputeRequest:
    polygon_id: str
    observations: list[SeriesPoint]
    targets: list[date]
    crop_type: str | None = None


@dataclass(slots=True)
class Prediction:
    date: date
    value: float
    confidence: float | None = None


@dataclass(slots=True)
class ImputeResult:
    predictions: list[Prediction]
    model_version: str
    source: str  # какая реализация ответила: внешний сервис или локальный baseline


@dataclass(slots=True)
class WeatherPoint:
    date: date
    temperature: float | None = None
    precipitation: float | None = None


@dataclass(slots=True)
class ForecastRequest:
    polygon_id: str
    observations: list[SeriesPoint]
    horizon_days: int = 14
    crop_type: str | None = None
    sowing_date: date | None = None
    weather_forecast: list[WeatherPoint] = dataclass_field(default_factory=list)
    # Ожидаемые значения нормы на даты прогноза. Локальный baseline опирается
    # на них напрямую; внешняя модель может использовать как признак.
    climatology: dict[date, tuple[float, float]] = dataclass_field(default_factory=dict)


@dataclass(slots=True)
class ForecastPoint:
    date: date
    value: float
    low: float | None = None
    high: float | None = None


@dataclass(slots=True)
class ForecastResult:
    points: list[ForecastPoint]
    model_version: str
    source: str
    direction: str | None = None       # ожидаемое направление динамики
    risk_level: str | None = None
    confidence: float | None = None
    # Если данных не хватило, прогноз не строится, а причина показывается
    # пользователю: отсутствие прогноза честнее выдуманного.
    insufficient_reason: str | None = None


@runtime_checkable
class MLClient(Protocol):
    """Клиент моделей."""

    name: str

    def is_available(self) -> bool: ...

    def impute(self, request: ImputeRequest) -> ImputeResult:
        """Восстановить значения `primary_ndvi` на запрошенные даты."""
        ...

    def forecast(self, request: ForecastRequest) -> ForecastResult:
        """Спрогнозировать NDVI на горизонт вперёд."""
        ...
