"""Схемы геометрии.

Полигон принимается и отдаётся в формате GeoJSON — на нём говорят и Leaflet
на фронтенде, и Overpass API, и Earth Engine. Внутреннее представление
(WKT для PostGIS) остаётся деталью слоя хранения.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

# Долгота, широта. Порядок именно такой — как требует спецификация GeoJSON.
Position = Annotated[list[float], Field(min_length=2, max_length=3)]


class PolygonGeometry(BaseModel):
    """Полигон GeoJSON. Внутренние кольца (дырки) допускаются."""

    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[Position]] = Field(min_length=1)

    @field_validator("coordinates")
    @classmethod
    def check_rings(cls, rings: list[list[Position]]) -> list[list[Position]]:
        for index, ring in enumerate(rings):
            # Замыкающая точка совпадает с первой, поэтому минимум для треугольника — 4.
            if len(ring) < 4:
                raise ValueError(
                    f"кольцо {index}: нужно минимум 4 точки, получено {len(ring)}"
                )
            if ring[0] != ring[-1]:
                raise ValueError(f"кольцо {index}: контур не замкнут")
            for lon, lat, *_ in ring:
                if not -180.0 <= lon <= 180.0:
                    raise ValueError(f"долгота вне диапазона: {lon}")
                if not -90.0 <= lat <= 90.0:
                    raise ValueError(f"широта вне диапазона: {lat}")
        return rings
