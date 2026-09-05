"""Радарные наблюдения Sentinel-1 через Google Earth Engine.

Работает с коллекцией `COPERNICUS/S1_GRD` — уже откалиброванной и приведённой
к рельефу. Сырые радарные данные обрабатывать не нужно: Earth Engine отдаёт
значения обратного рассеяния в децибелах, с убранным тепловым шумом и
ортотрансформированием по цифровой модели рельефа.

Зачем радар рядом с Sentinel-2. Оптика видит спектральное состояние листа,
радар — физическую структуру поверхности и растительного полога. Это два
независимых механизма измерения, поэтому совпадение аномалии в обоих
источниках резко повышает доверие к выводу. Плюс радар не зависит от облаков
и времени суток: там, где оптический ряд рвётся на две недели, радарный
продолжается.

Главное правило работы с Sentinel-1: **сравнивать между собой можно только
снимки одной геометрии съёмки**. Угол падения луча меняется от орбиты к орбите,
и уровень сигнала вместе с ним — на 1-3 дБ, что сопоставимо с настоящими
событиями на поле. Поэтому направление пролёта и относительный номер орбиты
приезжают вместе со значениями и участвуют в расчёте разностей.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from agropulse.providers.base import ProviderError, RadarObservation
from agropulse.providers.satellite_gee import _ensure_initialized, _is_configured

logger = logging.getLogger(__name__)

COLLECTION_S1 = "COPERNICUS/S1_GRD"

# Interferometric Wide — основной режим съёмки суши. Другие режимы (EW, SM)
# имеют иное разрешение и угол, и подмешивать их в один ряд нельзя.
INSTRUMENT_MODE = "IW"

# Нативное разрешение IW GRD.
SCALE_METERS = 10

# Радиус окна медианного фильтра против спекла. Спекл — мультипликативный шум,
# присущий любой когерентной съёмке: соседние пиксели однородного поля могут
# различаться на несколько децибел. Для медианы по всему полю он усредняется
# сам, но доля «слабых» пикселей без сглаживания превратилась бы в замер шума.
SPECKLE_FILTER_METERS = 30

# Внутренний отступ от границы поля. Пиксель размером 10 м на краю контура
# наполовину состоит из дороги, лесополосы или соседнего поля, а у радара
# такие объекты дают сильный отклик и смещают всю статистику.
EDGE_BUFFER_METERS = 20

# Ниже этой площади ядра отступ не применяется: у мелкого поля он съел бы
# весь контур. Такие поля считаются целиком, с оговоркой в качестве данных.
MIN_CORE_AREA_M2 = 2000.0

# Погрешность вычисления площади, м. Земной эллипсоид: точнее не нужно.
AREA_ERROR_MARGIN = 1.0

# Насколько пиксель должен быть слабее медианы поля, чтобы считаться слабым.
# 2 дБ — примерно полуторакратная разница в мощности отражённого сигнала,
# заметно больше остаточного спекла после сглаживания.
LOW_SIGNAL_DELTA_DB = 2.0

# Ниже этой доли покрытия поле попало на край полосы съёмки, и медиана
# посчитана по случайному куску контура.
MIN_VALID_FRACTION = 0.5


class GEERadarProvider:
    """Реализация RadarProvider поверх Earth Engine."""

    name = "s1_gee"

    def is_available(self) -> bool:
        return _is_configured()

    def fetch_series(
        self, geometry: dict, date_from: date, date_to: date
    ) -> list[RadarObservation]:
        _ensure_initialized()
        import ee

        region = ee.Geometry(geometry)
        core = _core_region(ee, region)

        scenes = (
            ee.ImageCollection(COLLECTION_S1)
            .filterBounds(region)
            .filterDate(date_from.isoformat(), date_to.isoformat())
            .filter(ee.Filter.eq("instrumentMode", INSTRUMENT_MODE))
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
        )

        features = ee.FeatureCollection(
            scenes.map(lambda image: _summarize_scene(ee, image, core))
        )

        try:
            payload = features.getInfo()
        except Exception as exc:
            raise ProviderError(f"запрос Sentinel-1 к Earth Engine не выполнен: {exc}") from exc

        raw = [f["properties"] for f in payload.get("features", [])]
        return _aggregate_by_date(raw, source=self.name)


def _core_region(ee, region):
    """Контур поля с внутренним отступом, если поле достаточно велико.

    Решение принимается на стороне Earth Engine: площадь поля здесь неизвестна,
    а отдельный запрос ради неё стоил бы столько же, сколько весь ряд.
    """
    core = region.buffer(-EDGE_BUFFER_METERS)
    return ee.Geometry(
        ee.Algorithms.If(
            core.area(AREA_ERROR_MARGIN).gt(MIN_CORE_AREA_M2),
            core,
            region,
        )
    )


def _summarize_scene(ee, image, region):
    """Свести одну радарную сцену к набору чисел по полю.

    Выполняется на серверах Google для каждой сцены, поэтому вся арифметика
    записана в терминах Earth Engine.
    """
    image = ee.Image(image)

    # Маска пригодности: за пределами полосы съёмки пикселей нет, и они должны
    # попасть в знаменатель покрытия, а не молча исчезнуть из него.
    coverage = image.select("VV").mask().rename("coverage").unmask(0, False)

    decibels = image.select(["VV", "VH"]).focal_median(
        radius=SPECKLE_FILTER_METERS, kernelType="circle", units="meters"
    )
    vv_db = decibels.select("VV")
    vh_db = decibels.select("VH")

    # RVI определён для линейных значений мощности, а коллекция хранит
    # децибелы. Считать индекс прямо по дБ нельзя: логарифм не переживает
    # сложения в знаменателе.
    vv_linear = ee.Image(10).pow(vv_db.divide(10))
    vh_linear = ee.Image(10).pow(vh_db.divide(10))
    rvi = (
        vh_linear.multiply(4).divide(vv_linear.add(vh_linear)).rename("rvi")
    )

    stacked = vv_db.addBands([vh_db, rvi])
    stats = stacked.reduceRegion(
        reducer=ee.Reducer.median().combine(
            reducer2=ee.Reducer.percentile([25, 75]), sharedInputs=True
        ),
        geometry=region,
        scale=SCALE_METERS,
        maxPixels=1e9,
        bestEffort=True,
    )

    # Доля слабых пикселей считается относительно медианы самого поля, а не
    # абсолютного порога: уровень сигнала зависит от культуры, влажности и
    # угла съёмки, и общего для всех полей значения не существует.
    #
    # Медианы может не быть вовсе: `filterBounds` отбирает сцены по рамке
    # снимка, а она шире области с данными, и поле может оказаться за краем
    # полосы съёмки. Подстановка нуля обязательна — без неё арифметика над
    # null роняет весь серверный запрос, а вместе с ним весь ряд поля
    # за все сезоны из-за одной такой сцены.
    raw_median = stats.get("VV_median")
    vv_median = ee.Number(ee.Algorithms.If(raw_median, raw_median, 0))
    weak = vv_db.lt(vv_median.subtract(LOW_SIGNAL_DELTA_DB)).rename("weak")

    fractions = coverage.addBands(weak).reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=region,
        scale=SCALE_METERS,
        maxPixels=1e9,
        bestEffort=True,
    )

    return ee.Feature(
        None,
        {
            "date": image.date().format("YYYY-MM-dd"),
            "scene_id": image.get("system:index"),
            "orbit_direction": image.get("orbitProperties_pass"),
            "relative_orbit": image.get("relativeOrbitNumber_start"),
            "vv": stats.get("VV_median"),
            "vh": stats.get("VH_median"),
            "rvi": stats.get("rvi_median"),
            "vv_p25": stats.get("VV_p25"),
            "vv_p75": stats.get("VV_p75"),
            "valid_fraction": fractions.get("coverage"),
            "low_signal_fraction": fractions.get("weak"),
        },
    )


def _aggregate_by_date(raw: list[dict], source: str) -> list[RadarObservation]:
    """Свести сцены к одной записи на дату.

    Полоса съёмки Sentinel-1 нарезана на срезы, и поле на границе среза
    попадает сразу в два снимка одного пролёта. Такие срезы объединяются
    с весом по доле покрытия.

    Отдельный случай — когда в один день поле сняли и на восходящей, и на
    нисходящей орбите. Усреднять их нельзя: у них разные углы падения луча,
    и среднее не соответствует ни одной реальной геометрии съёмки. Побеждает
    пролёт с большим покрытием, второй отбрасывается.
    """
    groups: dict[tuple[str, str | None, int | None], list[dict]] = {}
    for row in raw:
        day = row.get("date")
        if not day:
            continue
        key = (day, _orbit_direction(row), _relative_orbit(row))
        groups.setdefault(key, []).append(row)

    # Из нескольких пролётов одного дня остаётся один — с лучшим покрытием.
    best_by_date: dict[str, tuple[float, tuple, list[dict]]] = {}
    for key, rows in groups.items():
        day = key[0]
        coverage = sum((row.get("valid_fraction") or 0.0) for row in rows) / len(rows)
        current = best_by_date.get(day)
        if current is None or coverage > current[0]:
            best_by_date[day] = (coverage, key, rows)

    observations: list[RadarObservation] = []
    for day in sorted(best_by_date):
        coverage, key, rows = best_by_date[day]
        _, orbit_direction, relative_orbit = key

        observation = RadarObservation(
            date=datetime.strptime(day, "%Y-%m-%d").date(),
            source=source,
            orbit_direction=orbit_direction,
            relative_orbit=relative_orbit,
            valid_fraction=round(coverage, 4),
            scene_id=",".join(str(row["scene_id"]) for row in rows if row.get("scene_id")) or None,
        )

        # Нулевое покрытие означает, что данных над полем в этой сцене нет
        # вовсе: рамка снимка поле задевает, а полоса съёмки — нет. Такая
        # дата не пропуск в ряду, а чужая сцена, и в ряду ей не место.
        if coverage <= 0:
            continue

        if coverage < MIN_VALID_FRACTION:
            observation.missing_reason = (
                f"поле покрыто съёмкой на {coverage:.0%} при минимуме {MIN_VALID_FRACTION:.0%}"
            )
            observations.append(observation)
            continue

        weights = [(row.get("valid_fraction") or 0.0) for row in rows]
        vv = _weighted(rows, weights, "vv")
        vh = _weighted(rows, weights, "vh")
        p25 = _weighted(rows, weights, "vv_p25")
        p75 = _weighted(rows, weights, "vv_p75")

        observation.vv_median_db = _round(vv, 3)
        observation.vh_median_db = _round(vh, 3)
        observation.rvi_median = _round(_weighted(rows, weights, "rvi"), 4)
        observation.low_signal_fraction = _round(
            _weighted(rows, weights, "low_signal_fraction"), 4
        )
        if vv is not None and vh is not None:
            observation.vh_vv_difference_db = round(vh - vv, 3)
        if p25 is not None and p75 is not None:
            observation.spatial_iqr_db = round(p75 - p25, 3)

        observations.append(observation)

    return observations


def _orbit_direction(row: dict) -> str | None:
    value = row.get("orbit_direction")
    return str(value).lower() if value else None


def _relative_orbit(row: dict) -> int | None:
    value = row.get("relative_orbit")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _weighted(rows: list[dict], weights: list[float], key: str) -> float | None:
    """Среднее по срезам с весом по покрытию.

    Срез, зацепивший поле краем, не должен весить столько же, сколько срез,
    накрывший его целиком.
    """
    total = sum(
        weight for row, weight in zip(rows, weights, strict=True) if row.get(key) is not None
    )
    if total <= 0:
        return None
    accumulated = sum(
        row[key] * weight
        for row, weight in zip(rows, weights, strict=True)
        if row.get(key) is not None
    )
    return accumulated / total


def _round(value: float | None, digits: int) -> float | None:
    return round(value, digits) if value is not None else None
