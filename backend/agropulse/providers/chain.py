"""Выбор источника данных с автоматическим переключением.

Пайплайн не должен знать, откуда именно приехали данные. Здесь источники
перебираются по порядку предпочтения: первый успешный побеждает, отказы
копятся и возвращаются вместе с результатом, чтобы попасть в отчёт о качестве
данных и стать видимыми пользователю.

Это прямая реализация требования устойчивости: отказ одного источника
деградирует результат, но не останавливает обработку поля.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field as dataclass_field
from datetime import date
from typing import TypeVar

from agropulse.providers.base import (
    ProviderError,
    SatelliteObservation,
    WeatherObservation,
)
from agropulse.providers.satellite_gee import GEESatelliteProvider
from agropulse.providers.weather_openmeteo import OpenMeteoWeatherProvider

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(slots=True)
class SourceResult[T]:
    """Результат вместе с историей попыток."""

    items: list[T] = dataclass_field(default_factory=list)
    source: str | None = None
    errors: list[str] = dataclass_field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.source is not None


def _try_providers(
    providers: Sequence, call: Callable[[object], list[T]], what: str
) -> SourceResult[T]:
    result: SourceResult[T] = SourceResult()

    for provider in providers:
        try:
            if not provider.is_available():
                result.errors.append(f"{provider.name}: не сконфигурирован")
                continue
            items = call(provider)
        except ProviderError as exc:
            logger.warning("%s: источник %s не отработал: %s", what, provider.name, exc)
            result.errors.append(f"{provider.name}: {exc}")
            continue
        except Exception as exc:  # неожиданная ошибка не должна ронять всю обработку поля
            logger.exception("%s: источник %s упал неожиданно", what, provider.name)
            result.errors.append(f"{provider.name}: непредвиденная ошибка {exc}")
            continue

        if not items:
            result.errors.append(f"{provider.name}: данных нет за запрошенный период")
            continue

        result.items = items
        result.source = provider.name
        return result

    return result


def satellite_providers() -> list:
    """Источники спутниковых наблюдений.

    Сейчас только Earth Engine. Реализация поверх STAC существует
    (`providers/satellite_stac.py`) и проверена, но в цепочку сознательно
    не включена: она на порядок медленнее, а необходимости в ней пока нет.
    Чтобы задействовать её как резервный канал, достаточно дописать
    `STACSatelliteProvider()` в этот список.
    """
    return [GEESatelliteProvider()]


def weather_history_providers() -> list:
    """Историю погоды берём из Open-Meteo.

    Реализация поверх ERA5-Land в Earth Engine существует
    (`providers/weather_era5_gee.py`) и проверена, но в цепочку не включена:
    Open-Meteo отдаёт и архив, и прогноз одним API и без задержки в несколько
    суток. Чтобы задействовать запасной источник, достаточно дописать
    `ERA5GEEWeatherProvider()` в этот список.
    """
    return [OpenMeteoWeatherProvider()]


def weather_forecast_providers() -> list:
    """Прогноз умеет только Open-Meteo: в ERA5-Land будущего нет."""
    return [OpenMeteoWeatherProvider()]


def fetch_satellite_series(
    geometry: dict, date_from: date, date_to: date
) -> SourceResult[SatelliteObservation]:
    return _try_providers(
        satellite_providers(),
        lambda p: p.fetch_series(geometry, date_from, date_to),
        "спутниковые данные",
    )


def fetch_weather_history(
    lon: float, lat: float, date_from: date, date_to: date
) -> SourceResult[WeatherObservation]:
    return _try_providers(
        weather_history_providers(),
        lambda p: p.fetch_history(lon, lat, date_from, date_to),
        "история погоды",
    )


def fetch_weather_forecast(lon: float, lat: float, days: int) -> SourceResult[WeatherObservation]:
    return _try_providers(
        weather_forecast_providers(),
        lambda p: p.fetch_forecast(lon, lat, days),
        "прогноз погоды",
    )
