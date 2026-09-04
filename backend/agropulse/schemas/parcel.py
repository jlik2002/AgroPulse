"""Схемы поиска региона и готовых сельхозконтуров."""

from pydantic import BaseModel, Field

from agropulse.schemas.geo import PolygonGeometry


class RegionRead(BaseModel):
    """Найденный по названию регион."""

    display_name: str
    lon: float
    lat: float
    # Порядок: запад, юг, восток, север.
    bbox: tuple[float, float, float, float]
    kind: str | None = None


class ParcelRead(BaseModel):
    """Готовый контур сельхозугодья из открытого источника."""

    external_ref: str
    geometry: PolygonGeometry
    area_ha: float
    name: str | None = None
    crop: str | None = None


class ParcelSearchRequest(BaseModel):
    """Поиск контуров в прямоугольнике карты.

    Прямоугольник приходит из текущего вида карты, поэтому поиск не привязан
    ни к какому заранее заданному перечню территорий.
    """

    west: float = Field(ge=-180, le=180)
    south: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)
    limit: int = Field(default=50, ge=1, le=200)
