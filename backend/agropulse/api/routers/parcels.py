"""Поиск территории: регион по названию и готовые контуры полей.

Первый шаг пользовательского пути. Ни одна из операций не привязана к заранее
подготовленному перечню территорий: регион ищется по произвольному названию,
контуры — в произвольном прямоугольнике карты.
"""

import logging

from fastapi import APIRouter, HTTPException, Query, status

from agropulse.providers.base import ProviderError
from agropulse.providers.geocode_nominatim import NominatimGeocoder
from agropulse.providers.parcels_overpass import OverpassParcelProvider
from agropulse.schemas.parcel import ParcelRead, ParcelSearchRequest, RegionRead

logger = logging.getLogger(__name__)
router = APIRouter(tags=["parcels"])


@router.get("/regions/search", response_model=list[RegionRead])
def search_regions(
    q: str = Query(min_length=2, description="Название региона, района или населённого пункта"),
    limit: int = Query(default=5, ge=1, le=20),
) -> list[RegionRead]:
    """Найти регион по названию и получить его границы для карты."""
    try:
        results = NominatimGeocoder().search(q, limit=limit)
    except ProviderError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    return [
        RegionRead(
            display_name=item.display_name,
            lon=item.lon,
            lat=item.lat,
            bbox=item.bbox,
            kind=item.kind,
        )
        for item in results
    ]


@router.post("/parcels/search", response_model=list[ParcelRead])
def search_parcels(payload: ParcelSearchRequest) -> list[ParcelRead]:
    """Найти готовые контуры пашни в прямоугольнике карты.

    Полнота данных зависит от региона: в OpenStreetMap контуры размечены
    неравномерно. Поэтому пустой результат — нормальный ответ, а не ошибка,
    и пользователь всегда может нарисовать полигон вручную.
    """
    if payload.east <= payload.west or payload.north <= payload.south:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="некорректные границы прямоугольника"
        )

    bbox = (payload.west, payload.south, payload.east, payload.north)
    try:
        parcels = OverpassParcelProvider().search(bbox, limit=payload.limit)
    except ProviderError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    return [
        ParcelRead(
            external_ref=item.external_ref,
            geometry=item.geometry,
            area_ha=item.area_ha,
            name=item.name,
            crop=item.crop,
        )
        for item in parcels
    ]
