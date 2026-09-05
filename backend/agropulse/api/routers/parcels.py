"""Поиск территории: регион по названию и готовые контуры полей.

Первый шаг пользовательского пути. Ни одна из операций не привязана к заранее
подготовленному перечню территорий: регион ищется по произвольному названию,
контуры — в произвольном прямоугольнике карты.
"""

from fastapi import APIRouter, Query

from agropulse.api.deps import TerritoryServiceDep
from agropulse.schemas.parcel import ParcelRead, ParcelSearchRequest, RegionRead

router = APIRouter(tags=["parcels"])


@router.get("/regions/search", response_model=list[RegionRead])
def search_regions(
    service: TerritoryServiceDep,
    q: str = Query(min_length=2, description="Название региона, района или населённого пункта"),
    limit: int = Query(default=5, ge=1, le=20),
) -> list[RegionRead]:
    """Найти регион по названию и получить его границы для карты."""
    return [RegionRead.model_validate(item) for item in service.search_regions(q, limit)]


@router.post("/parcels/search", response_model=list[ParcelRead])
def search_parcels(
    payload: ParcelSearchRequest, service: TerritoryServiceDep
) -> list[ParcelRead]:
    """Найти готовые контуры пашни в прямоугольнике карты.

    Полнота данных зависит от региона: в OpenStreetMap контуры размечены
    неравномерно. Поэтому пустой результат — нормальный ответ, а не ошибка,
    и пользователь всегда может нарисовать полигон вручную.
    """
    parcels = service.search_parcels(
        west=payload.west,
        south=payload.south,
        east=payload.east,
        north=payload.north,
        limit=payload.limit,
    )
    return [ParcelRead.model_validate(parcel) for parcel in parcels]
