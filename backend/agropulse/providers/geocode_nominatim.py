"""Поиск региона по названию через Nominatim (OpenStreetMap).

Нужен для первого шага пользовательского пути: человек вводит название района
или населённого пункта, а сервис показывает карту нужного места и ищет там
сельхозконтуры. Привязки к конкретной стране нет — это прямое требование
работоспособности в любом регионе.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from agropulse.config import get_settings
from agropulse.providers import cache
from agropulse.providers.base import ProviderError

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 30 * 24 * 3600


@dataclass(slots=True)
class GeocodeResult:
    display_name: str
    lon: float
    lat: float
    # Границы в порядке (запад, юг, восток, север).
    bbox: tuple[float, float, float, float]
    kind: str | None = None


class NominatimGeocoder:
    name = "nominatim"

    def is_available(self) -> bool:
        return True

    def search(self, query: str, limit: int = 5) -> list[GeocodeResult]:
        settings = get_settings()
        params = {"q": query, "format": "jsonv2", "limit": limit, "polygon_geojson": 0}

        payload = cache.cached_call(
            provider=self.name,
            ttl_seconds=CACHE_TTL_SECONDS,
            loader=lambda: _request(settings.nominatim_url, params),
            **params,
        )

        results: list[GeocodeResult] = []
        for row in payload:
            # Nominatim отдаёт границы строками в порядке юг, север, запад, восток.
            south, north, west, east = (float(v) for v in row["boundingbox"])
            results.append(
                GeocodeResult(
                    display_name=row.get("display_name", query),
                    lon=float(row["lon"]),
                    lat=float(row["lat"]),
                    bbox=(west, south, east, north),
                    kind=row.get("type"),
                )
            )
        return results


def _request(url: str, params: dict) -> list:
    settings = get_settings()
    try:
        # Политика использования Nominatim требует осмысленного User-Agent,
        # анонимные запросы блокируются.
        response = httpx.get(
            url,
            params=params,
            timeout=settings.http_timeout_seconds,
            headers={"User-Agent": settings.http_user_agent},
            follow_redirects=True,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise ProviderError(f"Nominatim не ответил: {exc}") from exc
