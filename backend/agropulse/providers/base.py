"""Общие интерфейсы источников данных.

Каждый внешний источник спрятан за протоколом. Причина не в академической
чистоте: сервис обязан переживать отказ отдельного источника и работать в любом
регионе, а для этого нужна возможность подменить реализацию, не трогая пайплайн.
Основной канал спутниковых данных — Earth Engine, резервный — STAC.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable


class ProviderError(RuntimeError):
    """Источник не смог отдать данные.

    Пайплайн ловит это исключение, помечает поле причиной и пробует
    следующий источник, вместо того чтобы падать целиком.
    """


class ProviderUnavailable(ProviderError):
    """Источник не сконфигурирован или недоступен — пробовать его бессмысленно."""


@dataclass(slots=True)
class SatelliteObservation:
    """Наблюдение по полю за одну дату, усреднённое по пригодным пикселям."""

    date: date
    source: str
    ndvi_mean: float | None = None
    ndmi_mean: float | None = None
    evi_mean: float | None = None
    valid_fraction: float | None = None
    cloud_fraction: float | None = None
    scene_id: str | None = None
    # Заполняется, если пригодных пикселей оказалось слишком мало.
    missing_reason: str | None = None


@runtime_checkable
class SatelliteProvider(Protocol):
    """Источник спутниковых наблюдений."""

    name: str

    def is_available(self) -> bool:
        """Проверка конфигурации без обращения к сети."""
        ...

    def fetch_series(
        self, geometry: dict, date_from: date, date_to: date
    ) -> list[SatelliteObservation]:
        """Временной ряд средних значений индексов по полигону.

        Возвращает по одной записи на дату. Даты без пригодных наблюдений
        либо отсутствуют в результате, либо приходят с `missing_reason`.
        """
        ...


@dataclass(slots=True)
class WeatherObservation:
    """Погода за одну дату: суточные агрегаты по полигону."""

    date: date
    temperature: float | None = None
    precipitation: float | None = None
    is_forecast: bool = False


@runtime_checkable
class WeatherProvider(Protocol):
    """Источник исторической и прогнозной погоды."""

    name: str

    def is_available(self) -> bool: ...

    def fetch_history(
        self, lon: float, lat: float, date_from: date, date_to: date
    ) -> list[WeatherObservation]: ...

    def fetch_forecast(self, lon: float, lat: float, days: int) -> list[WeatherObservation]: ...
