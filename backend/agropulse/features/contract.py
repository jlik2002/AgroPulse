"""Единый построитель признаков для сервиса моделей.

Это единственное место, где формируется набор признаков, и оно используется
обоими сценариями: и веб-обработкой поля, и batch-инференсом по файлу
`private_features.csv`. Дублировать эту логику нельзя ни при каких
обстоятельствах.

Причина в главном техническом риске проекта. Модель обучается на подготовленном
организаторами датасете, а веб-сервис собирает данные из Earth Engine
самостоятельно. Если состав или семантика признаков разойдутся, модель
на живых данных вернёт правдоподобный, но неверный результат, и обнаружится
это в худший момент. Поэтому сервис моделей обязан отдавать список ожидаемых
признаков (`GET /v1/model-info`), а мы обязаны сверять его с тем, что строим.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FeatureRow:
    """Признаки одной строки: одно поле на одну дату."""

    date: date
    primary_ndvi: float | None
    features: dict[str, float | None]


def build_row(
    day: date,
    ndvi: float | None = None,
    ndmi: float | None = None,
    evi: float | None = None,
    temperature: float | None = None,
    precipitation: float | None = None,
    valid_fraction: float | None = None,
    cloud_fraction: float | None = None,
    climatology_mean: float | None = None,
    climatology_std: float | None = None,
    n_reference_years: int | None = None,
) -> FeatureRow:
    """Собрать признаки одной даты.

    Календарные признаки кодируются синусом и косинусом дня года, а не самим
    номером дня: иначе 31 декабря и 1 января оказались бы максимально далеки
    друг от друга, хотя фенологически это соседние даты.
    """
    day_of_year = day.timetuple().tm_yday
    angle = 2.0 * math.pi * day_of_year / 365.25

    features: dict[str, float | None] = {
        "year": float(day.year),
        "day_of_year": float(day_of_year),
        "doy_sin": round(math.sin(angle), 6),
        "doy_cos": round(math.cos(angle), 6),
        "ndmi": ndmi,
        "evi": evi,
        "t2m_mean": temperature,
        "tp_sum": precipitation,
        "valid_fraction": valid_fraction,
        "cloud_fraction": cloud_fraction,
        "climatology_mean": climatology_mean,
        "climatology_std": climatology_std,
        "n_reference_years": float(n_reference_years) if n_reference_years is not None else None,
    }
    return FeatureRow(date=day, primary_ndvi=ndvi, features=features)


def feature_names() -> list[str]:
    """Состав признаков, который строит сервис.

    Сверяется с `expected_features` из ответа сервиса моделей.
    """
    return list(build_row(date(2000, 1, 1)).features)


def compare_with_expected(expected: list[str]) -> tuple[bool, list[str], list[str]]:
    """Сверить наш набор признаков с ожидаемым моделью.

    Возвращает признак совпадения, а также списки недостающих и лишних имён.
    Расхождение не является фатальной ошибкой: модель может игнорировать лишние
    признаки. Но недостающие — повод предупредить громко, потому что именно они
    приводят к тихой порче результата.
    """
    ours = set(feature_names())
    theirs = set(expected)
    missing = sorted(theirs - ours)
    extra = sorted(ours - theirs)
    if missing:
        logger.warning(
            "Сервис моделей ожидает признаки, которых мы не строим: %s", ", ".join(missing)
        )
    return not missing, missing, extra
