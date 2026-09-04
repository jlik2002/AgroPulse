"""Работа с геометрией полей.

Три задачи: проверить корректность присланного полигона, посчитать его площадь
и переводить геометрию между GeoJSON (внешний формат) и WKB/WKT (формат PostGIS).

Площадь считается геодезически через pyproj, а не в квадратных градусах и не
запросом в базу. Градусы дали бы ошибку в разы в зависимости от широты, а поход
в базу не нужен: расчёт требуется и в задачах Celery, где сессии может не быть.
"""

from __future__ import annotations

from geoalchemy2.elements import WKBElement, WKTElement
from geoalchemy2.shape import to_shape
from pyproj import Geod
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry

from agropulse.schemas.geo import PolygonGeometry

SRID = 4326

# Границы разумного размера поля. Слишком мелкий полигон не покрыть даже
# несколькими пикселями Sentinel-2 (10 м), слишком крупный превращает запрос
# в Earth Engine в долгую и дорогую операцию без продуктового смысла.
MIN_AREA_HA = 0.1
MAX_AREA_HA = 50_000.0

_GEOD = Geod(ellps="WGS84")


class GeometryError(ValueError):
    """Полигон непригоден для анализа. Текст показывается пользователю."""


def geojson_to_shape(geometry: PolygonGeometry | dict) -> BaseGeometry:
    payload = geometry.model_dump() if isinstance(geometry, PolygonGeometry) else geometry
    return shape(payload)


def area_hectares(geom: BaseGeometry) -> float:
    """Геодезическая площадь в гектарах.

    Знак результата зависит от направления обхода кольца, поэтому берём модуль.
    """
    area_m2, _perimeter = _GEOD.geometry_area_perimeter(geom)
    return abs(area_m2) / 10_000.0


def validate_polygon(geometry: PolygonGeometry | dict) -> tuple[BaseGeometry, float]:
    """Проверить полигон и вернуть его вместе с площадью.

    Возбуждает GeometryError с понятным пользователю текстом — сообщение уходит
    в ответ API как есть.
    """
    try:
        geom = geojson_to_shape(geometry)
    except Exception as exc:
        raise GeometryError(f"не удалось разобрать геометрию: {exc}") from exc

    if geom.is_empty:
        raise GeometryError("полигон пустой")

    if not geom.is_valid:
        # Самая частая причина — самопересечение контура при ручном рисовании.
        from shapely.validation import explain_validity

        raise GeometryError(f"полигон некорректен: {explain_validity(geom)}")

    area = area_hectares(geom)
    if area < MIN_AREA_HA:
        raise GeometryError(
            f"площадь {area:.3f} га меньше минимальной {MIN_AREA_HA} га: "
            "поле не покрыть пикселями Sentinel-2"
        )
    if area > MAX_AREA_HA:
        raise GeometryError(
            f"площадь {area:.0f} га больше максимальной {MAX_AREA_HA:.0f} га: "
            "разбейте территорию на несколько полей"
        )
    return geom, area


def to_wkt_element(geom: BaseGeometry) -> WKTElement:
    """Геометрия в виде, пригодном для записи в колонку PostGIS."""
    return WKTElement(geom.wkt, srid=SRID)


def to_geojson(value: WKBElement | BaseGeometry) -> dict:
    """Геометрия из базы в GeoJSON без обращения к PostGIS."""
    geom = to_shape(value) if isinstance(value, WKBElement) else value
    return mapping(geom)
