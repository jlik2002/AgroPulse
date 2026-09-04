"""Готовые контуры сельхозполей из OpenStreetMap через Overpass API.

Второй сценарий работы с территорией: пользователь выбирает существующий контур
вместо ручного рисования. Полнота OSM сильно зависит от региона, поэтому выбор
готового контура остаётся удобством, а не обязательным шагом — ручное рисование
работает везде.

Из ответа отбираются только замкнутые way с тегом landuse=farmland, а также
внешние кольца мультиполигонов-отношений. Контуры неправдоподобного размера
отбрасываются: в OSM попадаются как обрывки в несколько соток, так и
сельхозмассивы в тысячи гектаров, ни те ни другие не являются полем.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
from shapely.geometry import Polygon, mapping

from agropulse.config import get_settings
from agropulse.geometry import MAX_AREA_HA, MIN_AREA_HA, area_hectares
from agropulse.providers import cache
from agropulse.providers.base import ProviderError

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 7 * 24 * 3600
QUERY_TIMEOUT_SECONDS = 90

# Ограничение площади поиска: слишком большой bbox уводит Overpass в таймаут
# и возвращает тысячи объектов, бесполезных для выбора одного поля.
MAX_BBOX_DEGREES = 0.5


@dataclass(slots=True)
class Parcel:
    """Найденный контур сельхозугодья."""

    external_ref: str
    geometry: dict
    area_ha: float
    name: str | None = None
    crop: str | None = None


class OverpassParcelProvider:
    name = "overpass"

    def is_available(self) -> bool:
        return True

    def search(
        self, bbox: tuple[float, float, float, float], limit: int = 50
    ) -> list[Parcel]:
        """Найти контуры пашни в прямоугольнике (запад, юг, восток, север)."""
        west, south, east, north = _clamp_bbox(bbox)

        # Overpass ожидает порядок юг, запад, север, восток.
        query = f"""
        [out:json][timeout:{QUERY_TIMEOUT_SECONDS}];
        (
          way["landuse"="farmland"]({south},{west},{north},{east});
          relation["landuse"="farmland"]({south},{west},{north},{east});
        );
        out geom;
        """.strip()

        settings = get_settings()
        payload = cache.cached_call(
            provider=self.name,
            ttl_seconds=CACHE_TTL_SECONDS,
            loader=lambda: _request(settings.overpass_url, query),
            bbox=[round(v, 5) for v in (west, south, east, north)],
        )

        parcels: list[Parcel] = []
        for element in payload.get("elements", []):
            parcel = _element_to_parcel(element)
            if parcel is not None:
                parcels.append(parcel)

        # Крупные поля показываем первыми: они интереснее для мониторинга
        # и с большей вероятностью являются реальным производственным участком.
        parcels.sort(key=lambda p: p.area_ha, reverse=True)
        return parcels[:limit]


def _clamp_bbox(bbox: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """Сжать слишком крупный прямоугольник к центру, сохранив центр поиска."""
    west, south, east, north = bbox
    if (east - west) <= MAX_BBOX_DEGREES and (north - south) <= MAX_BBOX_DEGREES:
        return bbox

    center_lon = (west + east) / 2
    center_lat = (south + north) / 2
    half = MAX_BBOX_DEGREES / 2
    logger.info("Область поиска сокращена до %s° вокруг центра", MAX_BBOX_DEGREES)
    return (center_lon - half, center_lat - half, center_lon + half, center_lat + half)


def _element_to_parcel(element: dict) -> Parcel | None:
    tags = element.get("tags") or {}
    element_type = element.get("type")

    if element_type == "way":
        ring = _ring_from_geometry(element.get("geometry"))
        rings = [ring] if ring else []
    elif element_type == "relation":
        # У мультиполигона берём внешние кольца; каждое становится отдельным контуром.
        rings = [
            _ring_from_geometry(member.get("geometry"))
            for member in element.get("members", [])
            if member.get("role") == "outer"
        ]
        rings = [ring for ring in rings if ring]
    else:
        return None

    for ring in rings:
        try:
            polygon = Polygon(ring)
        except Exception:
            continue
        if not polygon.is_valid or polygon.is_empty:
            continue

        area = area_hectares(polygon)
        if not (MIN_AREA_HA <= area <= MAX_AREA_HA):
            continue

        return Parcel(
            external_ref=f"{element_type}/{element.get('id')}",
            geometry=mapping(polygon),
            area_ha=round(area, 3),
            name=tags.get("name"),
            crop=tags.get("crop") or tags.get("produce"),
        )
    return None


def _ring_from_geometry(geometry: list | None) -> list[tuple[float, float]] | None:
    if not geometry or len(geometry) < 4:
        return None
    ring = [(point["lon"], point["lat"]) for point in geometry]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring if len(ring) >= 4 else None


def _request(url: str, query: str) -> dict:
    settings = get_settings()
    try:
        response = httpx.post(
            url,
            content=query.encode("utf-8"),
            timeout=QUERY_TIMEOUT_SECONDS + 30,
            headers={
                "User-Agent": settings.http_user_agent,
                "Content-Type": "text/plain; charset=utf-8",
            },
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise ProviderError(f"Overpass не ответил: {exc}") from exc
