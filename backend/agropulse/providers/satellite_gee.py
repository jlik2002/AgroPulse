"""Источник спутниковых наблюдений на базе Google Earth Engine.

Работает с коллекцией `COPERNICUS/S2_SR_HARMONIZED`. Именно harmonized-вариант,
а не обычный S2_SR: начиная с processing baseline 04.00 Copernicus сдвинул
значения отражения на 1000, и гармонизированная коллекция приводит все снимки
к единой шкале. Без этого ряд NDVI получил бы искусственный разрыв в начале 2022 года.

Ключевое архитектурное решение — весь расчёт выполняется на стороне Google, а
к нам приезжает только готовый временной ряд, одним запросом `getInfo()` на весь
период. Цикл по датам с отдельным запросом на каждую был бы на порядок медленнее
и быстро упёрся бы в квоты.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import date, datetime

from agropulse.config import get_settings
from agropulse.providers.base import (
    ProviderError,
    ProviderUnavailable,
    SatelliteObservation,
)

logger = logging.getLogger(__name__)

COLLECTION_S2 = "COPERNICUS/S2_SR_HARMONIZED"
COLLECTION_CLOUD_PROB = "COPERNICUS/S2_CLOUD_PROBABILITY"

# Классы маски Scene Classification Layer, непригодные для расчёта индексов:
# 0 — нет данных, 1 — насыщенный или дефектный пиксель, 3 — тень облака,
# 8 и 9 — облако средней и высокой вероятности, 10 — перистое облако, 11 — снег и лёд.
SCL_INVALID = [0, 1, 3, 8, 9, 10, 11]
# Подмножество, которое считаем именно облачностью (без снега и дефектов).
SCL_CLOUD = [3, 8, 9, 10]

# Порог вероятности облака по s2cloudless. Одной маски SCL недостаточно:
# она регулярно пропускает полупрозрачную дымку над полями.
CLOUD_PROBABILITY_THRESHOLD = 40

# Разрешение, на котором усредняются значения. 10 м — нативное для B4 и B8.
SCALE_METERS = 10

# Ниже этой доли пригодных пикселей среднее по полю не показательно:
# оно посчитано по случайным просветам между облаками.
MIN_VALID_FRACTION = 0.2

_init_lock = threading.Lock()
_initialized_pid: int | None = None


def _ensure_initialized() -> None:
    """Инициализировать Earth Engine один раз на процесс.

    Сравнение с PID обязательно: Celery использует prefork, и дочерний процесс
    унаследовал бы флаг инициализации вместе с непригодными после fork
    HTTP-соединениями родителя.
    """
    global _initialized_pid

    current_pid = os.getpid()
    if _initialized_pid == current_pid:
        return

    with _init_lock:
        if _initialized_pid == current_pid:
            return

        settings = get_settings()
        key_path = settings.gee_service_account_file
        if not os.path.isfile(key_path):
            raise ProviderUnavailable(
                f"ключ сервис-аккаунта Earth Engine не найден: {key_path}"
            )

        import json

        import ee

        try:
            with open(key_path) as handle:
                key_data = json.load(handle)
            account = key_data["client_email"]
            # Project ID из настроек имеет приоритет: ключ может принадлежать
            # одному проекту, а квота Earth Engine быть выделена другому.
            project = settings.gee_project or key_data.get("project_id")
            credentials = ee.ServiceAccountCredentials(account, key_path)
            ee.Initialize(credentials, project=project)
        except Exception as exc:
            raise ProviderUnavailable(f"не удалось инициализировать Earth Engine: {exc}") from exc

        _initialized_pid = current_pid
        logger.info("Earth Engine инициализирован в процессе %s", current_pid)


class GEESatelliteProvider:
    """Реализация SatelliteProvider поверх Earth Engine."""

    name = "s2_gee"

    def is_available(self) -> bool:
        return os.path.isfile(get_settings().gee_service_account_file)

    def fetch_series(
        self, geometry: dict, date_from: date, date_to: date
    ) -> list[SatelliteObservation]:
        _ensure_initialized()
        import ee

        region = ee.Geometry(geometry)
        # Верхняя граница берётся включительно, а filterDate исключает её.
        start = date_from.isoformat()
        end = date_to.isoformat()

        scenes = (
            ee.ImageCollection(COLLECTION_S2)
            .filterBounds(region)
            .filterDate(start, end)
        )
        cloud_probability = (
            ee.ImageCollection(COLLECTION_CLOUD_PROB)
            .filterBounds(region)
            .filterDate(start, end)
        )

        # s2cloudless лежит отдельной коллекцией, сцены сопоставляются по system:index.
        joined = ee.ImageCollection(
            ee.Join.saveFirst("cloud_probability").apply(
                primary=scenes,
                secondary=cloud_probability,
                condition=ee.Filter.equals(
                    leftField="system:index", rightField="system:index"
                ),
            )
        )

        features = ee.FeatureCollection(
            joined.map(lambda image: _summarize_scene(ee, image, region))
        )

        try:
            payload = features.getInfo()
        except Exception as exc:
            raise ProviderError(f"запрос к Earth Engine не выполнен: {exc}") from exc

        raw = [f["properties"] for f in payload.get("features", [])]
        return _aggregate_by_date(raw, source=self.name)


def _summarize_scene(ee, image, region):
    """Свести одну сцену к набору чисел по полигону.

    Функция выполняется на серверах Google для каждой сцены коллекции,
    поэтому вся арифметика записана в терминах Earth Engine, а не Python.
    """
    image = ee.Image(image)

    # --- маска пригодности ---
    scl = image.select("SCL")
    valid_by_scl = scl.remap(SCL_INVALID, [0] * len(SCL_INVALID), 1)

    probability = ee.Image(image.get("cloud_probability")).select("probability")
    valid_by_probability = probability.lt(CLOUD_PROBABILITY_THRESHOLD)

    # sameFootprint=False распространяет маску за пределы снимка: если полигон
    # выходит за край сцены, эти пиксели должны считаться непригодными,
    # а не молча выпадать из знаменателя.
    valid = valid_by_scl.And(valid_by_probability).rename("valid").unmask(0, False)

    cloud = (
        scl.remap(SCL_CLOUD, [1] * len(SCL_CLOUD), 0)
        .Or(probability.gte(CLOUD_PROBABILITY_THRESHOLD))
        .rename("cloud")
        .unmask(0, False)
    )

    # --- индексы ---
    # Отражение хранится целыми числами с коэффициентом 10000. Для NDVI и NDMI
    # это безразлично (нормированная разность), но EVI — нет: в его формуле
    # есть свободный член, и без приведения к диапазону 0..1 он теряет смысл.
    reflectance = image.select(["B2", "B4", "B8", "B11"]).multiply(0.0001)

    ndvi = reflectance.normalizedDifference(["B8", "B4"]).rename("ndvi")
    ndmi = reflectance.normalizedDifference(["B8", "B11"]).rename("ndmi")
    evi = reflectance.expression(
        "2.5 * (nir - red) / (nir + 6 * red - 7.5 * blue + 1)",
        {
            "nir": reflectance.select("B8"),
            "red": reflectance.select("B4"),
            "blue": reflectance.select("B2"),
        },
    ).rename("evi")

    indices = ndvi.addBands([ndmi, evi]).updateMask(valid)

    means = indices.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=region,
        scale=SCALE_METERS,
        maxPixels=1e9,
        bestEffort=True,
    )
    fractions = valid.addBands(cloud).reduceRegion(
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
            "ndvi": means.get("ndvi"),
            "ndmi": means.get("ndmi"),
            "evi": means.get("evi"),
            "valid_fraction": fractions.get("valid"),
            "cloud_fraction": fractions.get("cloud"),
        },
    )


def _aggregate_by_date(raw: list[dict], source: str) -> list[SatelliteObservation]:
    """Свести сцены к одной записи на дату.

    В один день полигон может попасть на несколько соседних тайлов Sentinel-2.
    Усредняем их с весом по доле пригодных пикселей: тайл, накрывший поле
    наполовину облаком, не должен тянуть среднее на себя.
    """
    by_date: dict[str, list[dict]] = {}
    for row in raw:
        day = row.get("date")
        if day:
            by_date.setdefault(day, []).append(row)

    observations: list[SatelliteObservation] = []
    for day in sorted(by_date):
        rows = by_date[day]
        weights = [(r.get("valid_fraction") or 0.0) for r in rows]
        total_weight = sum(weights)

        scene_ids = ",".join(str(r.get("scene_id")) for r in rows if r.get("scene_id"))
        valid_fraction = round(total_weight / len(rows), 4)
        cloud_values = [r.get("cloud_fraction") for r in rows if r.get("cloud_fraction") is not None]
        cloud_fraction = round(sum(cloud_values) / len(cloud_values), 4) if cloud_values else None

        observation = SatelliteObservation(
            date=datetime.strptime(day, "%Y-%m-%d").date(),
            source=source,
            valid_fraction=valid_fraction,
            cloud_fraction=cloud_fraction,
            scene_id=scene_ids or None,
        )

        if total_weight < MIN_VALID_FRACTION:
            # Данные за эту дату есть, но доверять среднему нельзя.
            # Точка попадёт в ряд как пропуск с указанием причины — так
            # пользователь видит разницу между «съёмки не было» и «съёмка была,
            # но поле закрыто облаками».
            observation.missing_reason = (
                f"пригодных пикселей {valid_fraction:.0%} при минимуме {MIN_VALID_FRACTION:.0%}"
            )
            observations.append(observation)
            continue

        for attribute, key in (("ndvi_mean", "ndvi"), ("ndmi_mean", "ndmi"), ("evi_mean", "evi")):
            weighted = sum(
                (r.get(key) or 0.0) * w
                for r, w in zip(rows, weights, strict=True)
                if r.get(key) is not None
            )
            available = sum(w for r, w in zip(rows, weights, strict=True) if r.get(key) is not None)
            if available > 0:
                setattr(observation, attribute, round(weighted / available, 6))

        observations.append(observation)

    return observations
