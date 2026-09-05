"""Геометрия, признаки модели и заглушка сервиса моделей."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from agropulse.errors import InvalidGeometryError
from agropulse.features import contract
from agropulse.geometry import MAX_AREA_HA, MIN_AREA_HA, area_hectares, centroid, validate_polygon

SQUARE = {
    "type": "Polygon",
    "coordinates": [
        [[37.60, 55.70], [37.62, 55.70], [37.62, 55.71], [37.60, 55.71], [37.60, 55.70]]
    ],
}


# ----------------------------------------------------------------------
# Геометрия
# ----------------------------------------------------------------------


def test_area_is_geodesic_not_in_square_degrees() -> None:
    """В квадратных градусах ошибка была бы кратной и зависела бы от широты."""
    from shapely.geometry import shape

    _, area = validate_polygon(SQUARE)

    # Прямоугольник 0.02° × 0.01° на широте 55.7°: около 1.25 × 1.11 км.
    assert 130.0 < area < 150.0
    # Тот же полигон у экватора заметно крупнее по площади.
    equatorial = {
        "type": "Polygon",
        "coordinates": [
            [[37.60, 0.0], [37.62, 0.0], [37.62, 0.01], [37.60, 0.01], [37.60, 0.0]]
        ],
    }
    assert area_hectares(shape(equatorial)) > area


def test_area_sign_does_not_depend_on_ring_direction() -> None:
    from shapely.geometry import shape

    reversed_ring = {
        "type": "Polygon",
        "coordinates": [list(reversed(SQUARE["coordinates"][0]))],
    }

    assert area_hectares(shape(reversed_ring)) == pytest.approx(
        area_hectares(shape(SQUARE))
    )


def test_self_intersecting_polygon_is_rejected() -> None:
    bowtie = {
        "type": "Polygon",
        "coordinates": [
            [[37.60, 55.70], [37.62, 55.71], [37.62, 55.70], [37.60, 55.71], [37.60, 55.70]]
        ],
    }

    with pytest.raises(InvalidGeometryError):
        validate_polygon(bowtie)


def test_area_bounds_are_enforced() -> None:
    tiny = {
        "type": "Polygon",
        "coordinates": [
            [[0.0, 0.0], [0.00001, 0.0], [0.00001, 0.00001], [0.0, 0.0]]
        ],
    }
    huge = {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [5.0, 0.0], [5.0, 5.0], [0.0, 5.0], [0.0, 0.0]]],
    }

    with pytest.raises(InvalidGeometryError, match=str(MIN_AREA_HA)):
        validate_polygon(tiny)
    with pytest.raises(InvalidGeometryError, match=f"{MAX_AREA_HA:.0f}"):
        validate_polygon(huge)


def test_centroid_is_inside_the_polygon() -> None:
    lon, lat = centroid(SQUARE)

    assert 37.60 < lon < 37.62
    assert 55.70 < lat < 55.71


# ----------------------------------------------------------------------
# Признаки модели
# ----------------------------------------------------------------------


def test_calendar_features_are_cyclic() -> None:
    """31 декабря и 1 января фенологически соседние даты, а не противоположные."""
    december = contract.build_row(date(2024, 12, 31)).features
    january = contract.build_row(date(2025, 1, 1)).features

    assert december["doy_sin"] == pytest.approx(january["doy_sin"], abs=0.05)
    assert december["doy_cos"] == pytest.approx(january["doy_cos"], abs=0.05)


def test_feature_names_are_stable() -> None:
    """Состав признаков — контракт с сервисом моделей."""
    assert contract.feature_names() == [
        "year",
        "day_of_year",
        "doy_sin",
        "doy_cos",
        "ndmi",
        "evi",
        "t2m_mean",
        "tp_sum",
        "valid_fraction",
        "cloud_fraction",
        "climatology_mean",
        "climatology_std",
        "n_reference_years",
    ]


def test_missing_feature_is_reported_loudly() -> None:
    """Недостающий признак тихо портит результат — о нём нужно знать."""
    matches, missing, extra = contract.compare_with_expected(
        contract.feature_names() + ["soil_moisture"]
    )

    assert matches is False
    assert missing == ["soil_moisture"]


def test_extra_features_are_not_a_failure() -> None:
    """Модель вправе игнорировать лишние признаки."""
    matches, missing, extra = contract.compare_with_expected(["year", "day_of_year"])

    assert matches is True
    assert missing == []
    assert "ndmi" in extra


# ----------------------------------------------------------------------
# Временная заглушка сервиса моделей
# ----------------------------------------------------------------------


def _series(count: int, step: int = 5) -> list:
    from agropulse.ml.client import SeriesPoint

    start = date(2024, 5, 1)
    return [
        SeriesPoint(date=start + timedelta(days=index * step), primary_ndvi=0.5 + index * 0.01)
        for index in range(count)
    ]


def test_stub_refuses_to_extrapolate() -> None:
    """Восстановленное значение обязано опираться на наблюдения с обеих сторон."""
    from agropulse.ml.baseline import BaselineMLClient
    from agropulse.ml.client import ImputeRequest

    observations = _series(6)
    beyond = observations[-1].date + timedelta(days=10)

    result = BaselineMLClient().impute(
        ImputeRequest(polygon_id="p", observations=observations, targets=[beyond])
    )

    assert result.predictions == []


def test_stub_needs_a_minimum_of_observations() -> None:
    from agropulse.ml.baseline import BaselineMLClient
    from agropulse.ml.client import ImputeRequest

    result = BaselineMLClient().impute(
        ImputeRequest(
            polygon_id="p",
            observations=_series(2),
            targets=[date(2024, 5, 3)],
        )
    )

    assert result.predictions == []


def test_stub_confidence_falls_with_distance_from_observations() -> None:
    from agropulse.ml.baseline import BaselineMLClient
    from agropulse.ml.client import ImputeRequest

    observations = _series(8, step=10)
    near = observations[0].date + timedelta(days=1)
    far = observations[0].date + timedelta(days=5)

    result = BaselineMLClient().impute(
        ImputeRequest(polygon_id="p", observations=observations, targets=[near, far])
    )

    by_date = {item.date: item for item in result.predictions}
    assert by_date[near].confidence > by_date[far].confidence


def test_forecast_reports_the_values_it_was_built_from() -> None:
    """Интерфейс объясняет прогноз его собственными причинами.

    Без этих величин раздел «Что влияет на прогноз» пришлось бы наполнять
    разложением текущего риска — то есть объяснять будущее прошлым.
    """
    from agropulse.ml.baseline import BaselineMLClient
    from agropulse.ml.client import ForecastRequest

    observations = _series(8)
    last = observations[-1].date
    # Норма покрывает горизонт и лежит заметно выше факта: поле отстаёт.
    climatology = {
        last + timedelta(days=offset): (0.9, 0.05) for offset in range(1, 16)
    }
    climatology.update({point.date: (0.9, 0.05) for point in observations})

    result = BaselineMLClient().forecast(
        ForecastRequest(
            polygon_id="p",
            observations=observations,
            horizon_days=14,
            climatology=climatology,
        )
    )

    assert result.points
    assert result.factors is not None
    assert result.factors["deviation_from_norm"] < 0
    assert result.factors["staleness_days"] == 1
    assert result.factors["observations_used"] == len(observations)
    assert "change_over_horizon" in result.factors
    # Отставание глубже 0.10 — модель обязана назвать риск высоким,
    # и раздел «Что влияет на прогноз» опирается на те же пороги.
    assert result.risk_level == "high"


def test_stub_declines_forecast_without_climatology() -> None:
    """Экстраполяция тренда в отрыве от сезонной кривой предсказала бы рост
    посреди уборки урожая."""
    from agropulse.ml.baseline import BaselineMLClient
    from agropulse.ml.client import ForecastRequest

    result = BaselineMLClient().forecast(
        ForecastRequest(polygon_id="p", observations=_series(8), horizon_days=14)
    )

    assert result.points == []
    assert result.insufficient_reason
