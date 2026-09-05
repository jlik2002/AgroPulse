"""Поиск территории: регион по названию и готовые контуры полей.

Первый шаг пользовательского пути. Ни одна из операций не привязана к заранее
подготовленному перечню территорий: регион ищется по произвольному названию,
контуры — в произвольном прямоугольнике карты.

Сервис ничего не хранит: у операций нет побочных эффектов, кроме кэша ответов
внешних источников. Он существует, чтобы роутер не создавал клиентов внешних
API сам и чтобы проверка запроса жила рядом с бизнес-правилом, а не в HTTP-слое.
"""

from __future__ import annotations

from agropulse.errors import InvalidBoundingBoxError
from agropulse.providers.geocode_nominatim import GeocodeResult, NominatimGeocoder
from agropulse.providers.parcels_overpass import OverpassParcelProvider, Parcel


class TerritoryService:
    def __init__(
        self,
        geocoder: NominatimGeocoder | None = None,
        parcels: OverpassParcelProvider | None = None,
    ) -> None:
        self._geocoder = geocoder or NominatimGeocoder()
        self._parcels = parcels or OverpassParcelProvider()

    def search_regions(self, query: str, limit: int) -> list[GeocodeResult]:
        """Найти регион по названию и получить его границы для карты."""
        return self._geocoder.search(query, limit=limit)

    def search_parcels(
        self, west: float, south: float, east: float, north: float, limit: int
    ) -> list[Parcel]:
        """Найти готовые контуры пашни в прямоугольнике карты.

        Полнота данных зависит от региона: в OpenStreetMap контуры размечены
        неравномерно. Поэтому пустой результат — нормальный ответ, а не ошибка,
        и пользователь всегда может нарисовать полигон вручную.
        """
        if east <= west or north <= south:
            raise InvalidBoundingBoxError(bbox=[west, south, east, north])
        return self._parcels.search((west, south, east, north), limit=limit)
