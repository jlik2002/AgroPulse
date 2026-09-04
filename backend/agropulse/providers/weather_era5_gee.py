"""Историческая погода из ERA5-Land через Google Earth Engine.

ВНИМАНИЕ: модуль в пайплайн не подключён. Написан и проверен как запасной
источник на случай недоступности Open-Meteo; чтобы задействовать, достаточно
дописать его в `providers/chain.py`.

Резервный источник погоды рядом с Open-Meteo. Нужен по двум причинам.

Во-первых, требование устойчивости: отказ одного внешнего источника не должен
останавливать анализ. Во-вторых, практическая — Open-Meteo доступен не из любой
сети, тогда как канал Earth Engine у сервиса уже есть и работает.

Ограничение источника: ERA5-Land содержит только прошлое. Прогноза погоды здесь
нет и быть не может, поэтому `fetch_forecast` честно сообщает о недоступности,
а не выдаёт экстраполяцию за прогноз.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from agropulse.providers import cache
from agropulse.providers.base import (
    ProviderError,
    ProviderUnavailable,
    WeatherObservation,
)
from agropulse.providers.satellite_gee import _ensure_initialized

logger = logging.getLogger(__name__)

COLLECTION_ERA5 = "ECMWF/ERA5_LAND/DAILY_AGGR"

# ERA5-Land хранит температуру в кельвинах, а осадки — в метрах водного столба.
KELVIN_OFFSET = 273.15
METERS_TO_MM = 1000.0

# Разрешение ERA5-Land около 11 км, поэтому точность выборки по полю избыточна:
# берём значение в одной точке — центроиде поля.
SCALE_METERS = 11_132

CACHE_TTL_SECONDS = 30 * 24 * 3600  # архив не пересматривается


class ERA5GEEWeatherProvider:
    """Реализация WeatherProvider поверх ERA5-Land в Earth Engine."""

    name = "era5_gee"

    def is_available(self) -> bool:
        import os

        from agropulse.config import get_settings

        return os.path.isfile(get_settings().gee_service_account_file)

    def fetch_history(
        self, lon: float, lat: float, date_from: date, date_to: date
    ) -> list[WeatherObservation]:
        params = {
            "lon": round(lon, 4),
            "lat": round(lat, 4),
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
        }
        payload = cache.cached_call(
            provider=self.name,
            ttl_seconds=CACHE_TTL_SECONDS,
            loader=lambda: self._fetch(lon, lat, date_from, date_to),
            **params,
        )
        return [
            WeatherObservation(
                date=date.fromisoformat(row["date"]),
                temperature=row["temperature"],
                precipitation=row["precipitation"],
                is_forecast=False,
            )
            for row in payload
        ]

    def fetch_forecast(self, lon: float, lat: float, days: int = 14) -> list[WeatherObservation]:
        raise ProviderUnavailable(
            "ERA5-Land содержит только исторические данные, прогноз недоступен"
        )

    def _fetch(self, lon: float, lat: float, date_from: date, date_to: date) -> list[dict]:
        _ensure_initialized()
        import ee

        point = ee.Geometry.Point([lon, lat])
        collection = (
            ee.ImageCollection(COLLECTION_ERA5)
            .filterDate(date_from.isoformat(), date_to.isoformat())
            .select(["temperature_2m", "total_precipitation_sum"])
        )

        def summarize(image):
            image = ee.Image(image)
            values = image.reduceRegion(
                reducer=ee.Reducer.first(),
                geometry=point,
                scale=SCALE_METERS,
                bestEffort=True,
            )
            return ee.Feature(
                None,
                {
                    "date": image.date().format("YYYY-MM-dd"),
                    "t2m": values.get("temperature_2m"),
                    "tp": values.get("total_precipitation_sum"),
                },
            )

        try:
            # Как и для снимков, весь ряд забирается одним запросом.
            payload = ee.FeatureCollection(collection.map(summarize)).getInfo()
        except Exception as exc:
            raise ProviderError(f"запрос ERA5-Land не выполнен: {exc}") from exc

        rows: list[dict] = []
        for feature in payload.get("features", []):
            properties = feature["properties"]
            day = properties.get("date")
            if not day:
                continue
            temperature = properties.get("t2m")
            precipitation = properties.get("tp")
            rows.append(
                {
                    "date": day,
                    "temperature": (
                        round(temperature - KELVIN_OFFSET, 2) if temperature is not None else None
                    ),
                    "precipitation": (
                        round(precipitation * METERS_TO_MM, 2)
                        if precipitation is not None
                        else None
                    ),
                }
            )
        rows.sort(key=lambda item: datetime.strptime(item["date"], "%Y-%m-%d"))
        return rows
