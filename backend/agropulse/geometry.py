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
from shapely.validation import explain_validity

from agropulse.errors import InvalidGeometryError
from agropulse.schemas.geo import PolygonGeometry

SRID = 4326

# Границы разумного размера поля. Слишком мелкий полигон не покрыть даже
# несколькими пикселями Sentinel-2 (10 м), слишком крупный превращает запрос
# в Earth Engine в долгую и дорогую операцию без продуктового смысла.
MIN_AREA_HA = 0.1
MAX_AREA_HA = 50_000.0

_GEOD = Geod(ellps="WGS84")


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

    Возбуждает `InvalidGeometryError` с понятным пользователю текстом:
    сообщение уходит в ответ API как есть, поэтому оно написано для человека,
    а машиночитаемым остаётся код ошибки.
    """
    try:
        geom = geojson_to_shape(geometry)
    except Exception as exc:
        raise InvalidGeometryError(f"не удалось разобрать геометрию: {exc}") from exc

    if geom.is_empty:
        raise InvalidGeometryError("полигон пустой")

    if not geom.is_valid:
        # Самая частая причина — самопересечение контура при ручном рисовании.
        raise InvalidGeometryError(f"полигон некорректен: {explain_validity(geom)}")

    area = area_hectares(geom)
    if area < MIN_AREA_HA:
        raise InvalidGeometryError(
            f"площадь {area:.3f} га меньше минимальной {MIN_AREA_HA} га: "
            "поле не покрыть пикселями Sentinel-2"
        )
    if area > MAX_AREA_HA:
        raise InvalidGeometryError(
            f"площадь {area:.0f} га больше максимальной {MAX_AREA_HA:.0f} га: "
            "разбейте территорию на несколько полей"
        )
    return geom, area


def to_wkt_element(geom: BaseGeometry) -> WKTElement:
    """Геометрия в виде, пригодном для записи в колонку PostGIS."""
    return WKTElement(geom.wkt, srid=SRID)


def to_geojson(value: WKBElement | WKTElement | BaseGeometry) -> dict:
    """Геометрия в GeoJSON без обращения к PostGIS.

    Принимаются оба представления GeoAlchemy2. Разница не теоретическая:
    только что записанное поле держит в атрибуте WKT, который мы сами туда
    положили, а прочитанное из базы — WKB. Обрабатывать только второй случай
    означало бы падение при ответе на POST, но не на GET.
    """
    geom = to_shape(value) if isinstance(value, WKBElement | WKTElement) else value
    return mapping(geom)


def centroid(geometry: PolygonGeometry | dict | BaseGeometry) -> tuple[float, float]:
    """Центр полигона в порядке (долгота, широта).

    Нужен там, где данные запрашиваются по точке, а не по контуру: погода
    отдаётся на координату, и брать её в углу поля неправильно.
    """
    geom = geometry if isinstance(geometry, BaseGeometry) else geojson_to_shape(geometry)
    point = geom.centroid
    return point.x, point.y
