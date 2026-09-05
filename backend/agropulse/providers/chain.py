"""Выбор источника данных с автоматическим переключением.

Пайплайн не должен знать, откуда именно приехали данные. Здесь источники
перебираются по порядку предпочтения: первый успешный побеждает, отказы
копятся и возвращаются вместе с результатом, чтобы попасть в отчёт о качестве
данных и стать видимыми пользователю.

Это прямая реализация требования устойчивости: отказ одного источника
деградирует результат, но не останавливает обработку поля.

Отказ источника и отсутствие данных за период разделены. Разница нужна
задаче: отказ имеет смысл повторить позже, а пустой период не изменится,
сколько задачу ни перезапускай.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date

from agropulse.providers.base import (
    ProviderError,
    RadarObservation,
    SatelliteObservation,
    WeatherObservation,
)
from agropulse.providers.radar_gee import GEERadarProvider
from agropulse.providers.satellite_gee import GEESatelliteProvider
from agropulse.providers.weather_openmeteo import OpenMeteoWeatherProvider

logger = logging.getLogger(__name__)

EMPTY_PERIOD_MESSAGE = "данных нет за запрошенный период"


@dataclass(slots=True)
class SourceResult[T]:
    """Результат вместе с историей попыток."""

    items: list[T] = dataclass_field(default_factory=list)
    source: str | None = None
    # Источники, ответившие ошибкой: не сконфигурированы, недоступны, упали.
    failures: list[str] = dataclass_field(default_factory=list)
    # Источники, ответившие штатно, но не имеющие данных за период.
    empty_sources: list[str] = dataclass_field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.source is not None

    @property
    def is_permanently_empty(self) -> bool:
        """Все источники ответили, и ни у одного нет данных за период.

        Повторять задачу в этом случае бессмысленно: за прошедший период
        снимки не появятся.
        """
        return not self.ok and bool(self.empty_sources) and not self.failures

    @property
    def errors(self) -> list[str]:
        """История попыток для отчёта о качестве данных."""
        return self.failures + [
            f"{name}: {EMPTY_PERIOD_MESSAGE}" for name in self.empty_sources
        ]


def _try_providers[T](
    providers: Sequence, call: Callable[[object], list[T]], what: str
) -> SourceResult[T]:
    result: SourceResult[T] = SourceResult()

    for provider in providers:
        try:
            if not provider.is_available():
                result.failures.append(f"{provider.name}: не сконфигурирован")
                continue
            items = call(provider)
        except ProviderError as exc:
            logger.warning(
                "provider_failed",
                extra={"kind": what, "provider": provider.name, "error": str(exc)},
            )
            result.failures.append(f"{provider.name}: {exc}")
            continue
        except Exception as exc:
            # Неожиданная ошибка источника не должна ронять обработку поля:
            # для этого и существует цепочка. Стек попадает в лог целиком.
            logger.exception(
                "provider_crashed", extra={"kind": what, "provider": provider.name}
            )
            result.failures.append(f"{provider.name}: непредвиденная ошибка {exc}")
            continue

        if not items:
            result.empty_sources.append(provider.name)
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


def radar_providers() -> list:
    """Источники радарных наблюдений.

    Резервного канала нет и он не нужен: радар — дополнение к оптике, а не её
    замена. Отказ этого источника снижает уверенность выводов, но не мешает
    посчитать поле, поэтому цепочка из одного элемента здесь не компромисс.
    """
    return [GEERadarProvider()]


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
        lambda provider: provider.fetch_series(geometry, date_from, date_to),
        "satellite",
    )


def fetch_radar_series(
    geometry: dict, date_from: date, date_to: date
) -> SourceResult[RadarObservation]:
    return _try_providers(
        radar_providers(),
        lambda provider: provider.fetch_series(geometry, date_from, date_to),
        "radar",
    )


def fetch_weather_history(
    lon: float, lat: float, date_from: date, date_to: date
) -> SourceResult[WeatherObservation]:
    return _try_providers(
        weather_history_providers(),
        lambda provider: provider.fetch_history(lon, lat, date_from, date_to),
        "weather_history",
    )


def fetch_weather_forecast(lon: float, lat: float, days: int) -> SourceResult[WeatherObservation]:
    return _try_providers(
        weather_forecast_providers(),
        lambda provider: provider.fetch_forecast(lon, lat, days),
        "weather_forecast",
    )
