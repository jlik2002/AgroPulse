"""Погода из Open-Meteo: исторический архив и прогноз.

Выбор источника не случаен. В Earth Engine есть ERA5-Land, но только для
прошлого — прогноза на 14 дней там нет, а он нужен для оценки риска. Open-Meteo
отдаёт и переработанный архив ERA5, и прогноз одним API, без ключа и с покрытием
всей планеты, что важно для требования работать в любом регионе.

Тонкость архива: он отстаёт от текущей даты на несколько суток. Поэтому свежий
хвост запрашивается у прогнозного эндпоинта через параметр `past_days`, который
отдаёт уже случившуюся погоду. Без этого последние дни ряда были бы пустыми
именно там, где аномалия наиболее интересна.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import httpx

from agropulse.config import get_settings
from agropulse.providers import cache
from agropulse.providers.base import ProviderError, WeatherObservation

logger = logging.getLogger(__name__)

# Суточные переменные: средняя температура на 2 м и сумма осадков.
DAILY_VARIABLES = "temperature_2m_mean,precipitation_sum"

# Задержка архива ERA5 в Open-Meteo. Всё, что свежее, берём у прогнозного API.
ARCHIVE_LAG_DAYS = 6
# Максимальная глубина past_days у прогнозного эндпоинта.
MAX_PAST_DAYS = 92

CACHE_TTL_ARCHIVE = 30 * 24 * 3600   # архив не меняется
CACHE_TTL_FORECAST = 3 * 3600        # прогноз устаревает быстро


class OpenMeteoWeatherProvider:
    """Реализация WeatherProvider поверх Open-Meteo."""

    name = "open_meteo"

    def is_available(self) -> bool:
        # Ключ не нужен, поэтому источник считается доступным всегда;
        # реальная недоступность выяснится при запросе.
        return True

    # ------------------------------------------------------------------
    # История
    # ------------------------------------------------------------------

    def fetch_history(
        self, lon: float, lat: float, date_from: date, date_to: date
    ) -> list[WeatherObservation]:
        cutoff = date.today() - timedelta(days=ARCHIVE_LAG_DAYS)
        observations: list[WeatherObservation] = []

        if date_from <= cutoff:
            observations += self._fetch_archive(lon, lat, date_from, min(date_to, cutoff))

        if date_to > cutoff:
            recent_from = max(date_from, cutoff + timedelta(days=1))
            observations += self._fetch_recent(lon, lat, recent_from, date_to)

        # Хвост архива и голова свежего запроса могут пересечься — оставляем
        # по одной записи на дату, предпочитая архивную как более точную.
        unique: dict[date, WeatherObservation] = {}
        for item in observations:
            unique.setdefault(item.date, item)
        return [unique[day] for day in sorted(unique)]

    def _fetch_archive(
        self, lon: float, lat: float, date_from: date, date_to: date
    ) -> list[WeatherObservation]:
        settings = get_settings()
        params = {
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "start_date": date_from.isoformat(),
            "end_date": date_to.isoformat(),
            "daily": DAILY_VARIABLES,
            "timezone": "UTC",
        }
        payload = cache.cached_call(
            provider=f"{self.name}_archive",
            ttl_seconds=CACHE_TTL_ARCHIVE,
            loader=lambda: _request(settings.open_meteo_archive_url, params),
            **params,
        )
        return _parse_daily(payload, is_forecast=False)

    def _fetch_recent(
        self, lon: float, lat: float, date_from: date, date_to: date
    ) -> list[WeatherObservation]:
        """Свежие уже случившиеся дни, которых ещё нет в архиве."""
        past_days = min((date.today() - date_from).days + 1, MAX_PAST_DAYS)
        if past_days <= 0:
            return []

        settings = get_settings()
        params = {
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "daily": DAILY_VARIABLES,
            "past_days": past_days,
            "forecast_days": 1,
            "timezone": "UTC",
        }
        payload = cache.cached_call(
            provider=f"{self.name}_recent",
            ttl_seconds=CACHE_TTL_FORECAST,
            loader=lambda: _request(settings.open_meteo_forecast_url, params),
            **params,
        )
        return [
            item
            for item in _parse_daily(payload, is_forecast=False)
            if date_from <= item.date <= date_to
        ]

    # ------------------------------------------------------------------
    # Прогноз
    # ------------------------------------------------------------------

    def fetch_forecast(self, lon: float, lat: float, days: int = 14) -> list[WeatherObservation]:
        settings = get_settings()
        params = {
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "daily": DAILY_VARIABLES,
            "forecast_days": min(days, 16),
            "timezone": "UTC",
        }
        payload = cache.cached_call(
            provider=f"{self.name}_forecast",
            ttl_seconds=CACHE_TTL_FORECAST,
            loader=lambda: _request(settings.open_meteo_forecast_url, params),
            **params,
        )
        today = date.today()
        return [
            item for item in _parse_daily(payload, is_forecast=True) if item.date >= today
        ]


def _request(url: str, params: dict) -> dict:
    settings = get_settings()
    try:
        response = httpx.get(
            url,
            params=params,
            timeout=settings.http_timeout_seconds,
            headers={"User-Agent": settings.http_user_agent},
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise ProviderError(f"Open-Meteo не ответил: {exc}") from exc


def _parse_daily(payload: dict, is_forecast: bool) -> list[WeatherObservation]:
    daily = payload.get("daily") or {}
    days = daily.get("time") or []
    temperatures = daily.get("temperature_2m_mean") or []
    precipitation = daily.get("precipitation_sum") or []

    observations: list[WeatherObservation] = []
    for index, day in enumerate(days):
        observations.append(
            WeatherObservation(
                date=date.fromisoformat(day),
                temperature=_at(temperatures, index),
                precipitation=_at(precipitation, index),
                is_forecast=is_forecast,
            )
        )
    return observations


def _at(values: list, index: int) -> float | None:
    if index >= len(values):
        return None
    value = values[index]
    return float(value) if value is not None else None
