"""Расчётное ядро: климатическая норма, аномалии, составной риск.

Модульные тесты, не требующие инфраструктуры. Проверяются продуктовые правила,
а не формулы ради формул: отсутствие нормы честнее выдуманной, одиночный выброс
не является событием, полю без данных риск не выставляется.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from agropulse.analytics import anomalies as anomalies_module
from agropulse.analytics import climatology as climatology_module
from agropulse.analytics import risk as risk_module
from agropulse.analytics.anomalies import SeriesSample
from agropulse.db.models import AnomalySeverity, FieldStatus, ValueType

# Сезонный ход NDVI: голая почва, всходы и рост, плато, созревание, стерня.
# Форма кусочно-линейная намеренно — на ней окно нормы даёт ровно то значение,
# которое в этой фазе и наблюдалось, поэтому здоровый сезон не должен давать
# ни одного отклонения. Любая найденная аномалия в таком ряду означает ошибку
# алгоритма, а не особенность тестовых данных.
BARE_SOIL = 0.20
PEAK = 0.75
RIPENING_END = 0.25

# Даты задаются днём года, а не смещением от 1 апреля: иначе високосный год
# сдвинул бы фазы относительно остальных, и сравнение поля с собой поехало бы.
SEASON_DAYS_OF_YEAR = [91 + index * 5 for index in range(40)]


def _season_values() -> list[float]:
    values = []
    for index in range(40):
        if index < 8:
            values.append(BARE_SOIL)
        elif index < 16:
            values.append(BARE_SOIL + (PEAK - BARE_SOIL) * (index - 8) / 8)
        elif index < 26:
            values.append(PEAK)
        elif index < 34:
            values.append(PEAK - (PEAK - RIPENING_END) * (index - 26) / 8)
        else:
            values.append(BARE_SOIL)
    return [round(value, 4) for value in values]


SEASON_VALUES = _season_values()


def season_curve(year: int, shift: float = 0.0) -> list[tuple[date, float]]:
    """Сезонный ход NDVI одного года."""
    return [
        (date(year, 1, 1) + timedelta(days=day_of_year - 1), round(value + shift, 4))
        for day_of_year, value in zip(SEASON_DAYS_OF_YEAR, SEASON_VALUES, strict=True)
    ]


def samples_from(curve: list[tuple[date, float]]) -> list[SeriesSample]:
    return [
        SeriesSample(date=day, ndvi=value, value_type=ValueType.OBSERVED)
        for day, value in curve
    ]


# ----------------------------------------------------------------------
# Климатология
# ----------------------------------------------------------------------


def test_climatology_needs_history() -> None:
    """Без собственной истории поля норма не строится, и это заявляется явно."""
    result = climatology_module.build(
        history=[(date(2024, 6, 1), 0.5)],
        target_dates=[date(2024, 6, 1)],
        sowing_date=None,
    )

    assert result.available is False
    assert result.reason


def test_climatology_excludes_analysed_year() -> None:
    """Иначе аномалия вошла бы в собственную норму и замаскировала себя."""
    history = season_curve(2021) + season_curve(2022) + season_curve(2023)
    anomalous_year = [(day, 0.05) for day, _ in season_curve(2024)]

    result = climatology_module.build(
        history=history + anomalous_year,
        target_dates=[day for day, _ in anomalous_year],
        sowing_date=None,
        exclude_year=2024,
    )

    assert result.available is True
    assert result.seasons_used == 3
    # Середина сезона: у здоровых лет здесь плато.
    midseason = anomalous_year[20][0]
    point = result.estimate(climatology_module.phase_of(midseason))
    assert point is not None
    # Норма построена по здоровым сезонам, а не по провалившемуся.
    assert point.mean > 0.4


def test_climatology_keeps_standard_deviation_off_zero() -> None:
    """В стабильных фазах знаменатель z-score не должен стремиться к нулю."""
    flat = [(date(year, 6, 1) + timedelta(days=offset), 0.5)
            for year in (2021, 2022, 2023)
            for offset in range(5)]

    result = climatology_module.build(
        history=flat, target_dates=[date(2024, 6, 1)], sowing_date=None, exclude_year=2024
    )

    point = result.estimate(climatology_module.phase_of(date(2024, 6, 1)))
    assert point.std >= climatology_module.MIN_STD


def test_day_of_year_is_cyclic() -> None:
    """5 января и конец декабря — соседние фазы, а не противоположные."""
    assert climatology_module.phase_of(date(2024, 1, 1)) == 1
    assert climatology_module.phase_of(date(2024, 12, 31)) == 366


# ----------------------------------------------------------------------
# Аномалии
# ----------------------------------------------------------------------


@pytest.fixture
def healthy_climatology() -> climatology_module.Climatology:
    history = season_curve(2021) + season_curve(2022) + season_curve(2023)
    return climatology_module.build(
        history=history,
        target_dates=[day for day, _ in season_curve(2024)],
        sowing_date=None,
        exclude_year=2024,
    )


def test_no_anomalies_on_a_normal_season(healthy_climatology) -> None:
    periods, zscores = anomalies_module.detect(
        samples_from(season_curve(2024)), healthy_climatology, None
    )

    assert periods == []
    assert zscores


def test_sustained_depression_becomes_an_event(healthy_climatology) -> None:
    curve = season_curve(2024)
    depressed = [
        (day, value - 0.25 if 17 <= index <= 24 else value)
        for index, (day, value) in enumerate(curve)
    ]

    periods, _ = anomalies_module.detect(
        samples_from(depressed), healthy_climatology, None
    )

    assert periods
    worst = periods[0]
    assert worst.max_zscore < anomalies_module.Z_MODERATE
    assert worst.duration_days >= anomalies_module.MIN_DURATION_DAYS


def test_single_outlier_is_not_an_event(healthy_climatology) -> None:
    """Одиночный провал чаще означает недомаскированное облако, чем угнетение."""
    curve = season_curve(2024)
    with_outlier = [
        (day, 0.05 if day == curve[20][0] else value) for day, value in curve
    ]

    periods, _ = anomalies_module.detect(
        samples_from(with_outlier), healthy_climatology, None
    )

    assert periods == []


def test_positive_deviation_creates_no_event(healthy_climatology) -> None:
    """Поле лучше нормы — не повод отправлять агронома."""
    curve = [(day, min(value + 0.2, 1.0)) for day, value in season_curve(2024)]

    periods, _ = anomalies_module.detect(samples_from(curve), healthy_climatology, None)

    assert periods == []


def test_deep_deviation_is_marked_critical(healthy_climatology) -> None:
    curve = [
        (day, 0.05 if 17 <= index <= 24 else value)
        for index, (day, value) in enumerate(season_curve(2024))
    ]

    periods, _ = anomalies_module.detect(samples_from(curve), healthy_climatology, None)

    assert periods[0].severity == AnomalySeverity.CRITICAL


def test_event_reports_how_much_of_it_was_interpolated(healthy_climatology) -> None:
    """Состав события сообщается честно: сколько в нём измеренного,
    сколько дорисованного.

    Сам вывод о доверии здесь не делается — этим занимается
    `analytics/trust.py` по независимым источникам. Раньше он делался прямо
    тут, числом `confidence`, и опирался на долю восстановленных значений.
    Доля эта равна примерно 0,8 у любого события по построению: восстановление
    заполняет каждый день периода, а Sentinel-2 летает раз в пять суток.
    Показатель получался одинаковым у всех событий и уверенности не измерял.
    """
    curve = [
        (day, value - 0.25 if 17 <= index <= 24 else value)
        for index, (day, value) in enumerate(season_curve(2024))
    ]

    observed = samples_from(curve)
    restored = [
        SeriesSample(date=s.date, ndvi=s.ndvi, value_type=ValueType.RESTORED)
        for s in observed
    ]

    by_observation, _ = anomalies_module.detect(observed, healthy_climatology, None)
    by_restoration, _ = anomalies_module.detect(restored, healthy_climatology, None)

    assert by_observation[0].restored_fraction == 0.0
    assert by_restoration[0].restored_fraction == 1.0


def test_crop_rotation_is_recognised_by_curve_shape(healthy_climatology) -> None:
    """Смена культуры отличается формой кривой, а не глубиной отклонения.

    Норма поля имеет пик в середине сезона. Кривая с обратной формой
    не является угнетением — это другая культура.
    """
    # Обратная форма кривой: пик там, где у нормы низ.
    curve = [(day, round(PEAK + BARE_SOIL - value, 4)) for day, value in season_curve(2024)]

    mismatch, correlation = anomalies_module.detect_phase_mismatch(
        samples_from(curve), healthy_climatology
    )

    assert mismatch is True
    assert correlation < anomalies_module.PHASE_MISMATCH_CORRELATION


def test_matching_season_is_not_a_rotation(healthy_climatology) -> None:
    """Угнетённое поле повторяет форму своей нормы, просто идёт ниже."""
    curve = [(day, round(max(value - 0.1, 0.0), 4)) for day, value in season_curve(2024)]

    mismatch, correlation = anomalies_module.detect_phase_mismatch(
        samples_from(curve), healthy_climatology
    )

    assert mismatch is False
    assert correlation > anomalies_module.PHASE_MISMATCH_CORRELATION


# ----------------------------------------------------------------------
# Риск
# ----------------------------------------------------------------------


def test_no_risk_score_without_enough_observations() -> None:
    """Выдуманный балл хуже честного «данных не хватает»."""
    assessment = risk_module.assess(
        anomalies=[],
        recent_zscores=[],
        observed_count=2,
        mean_valid_fraction=0.9,
        restored_fraction=0.0,
        climatology_available=True,
    )

    assert assessment.score is None
    assert assessment.status == FieldStatus.INSUFFICIENT_DATA
    assert assessment.insufficient_reason


def test_no_risk_score_without_climatology() -> None:
    assessment = risk_module.assess(
        anomalies=[],
        recent_zscores=[],
        observed_count=20,
        mean_valid_fraction=0.9,
        restored_fraction=0.0,
        climatology_available=False,
    )

    assert assessment.score is None
    assert assessment.status == FieldStatus.INSUFFICIENT_DATA


def test_healthy_field_gets_normal_status() -> None:
    assessment = risk_module.assess(
        anomalies=[],
        recent_zscores=[(date(2024, 6, 1), 0.2)],
        observed_count=20,
        mean_valid_fraction=0.95,
        restored_fraction=0.0,
        climatology_available=True,
    )

    assert assessment.status == FieldStatus.NORMAL
    assert assessment.score == 0.0
    assert assessment.explanation


def test_risk_breakdown_sums_to_score() -> None:
    """Балл должен быть объяснимым: он равен сумме показанных вкладов."""
    anomaly = anomalies_module.AnomalyPeriod(
        start_date=date(2024, 6, 1),
        end_date=date(2024, 6, 25),
        duration_days=25,
        severity=AnomalySeverity.CRITICAL,
        max_zscore=-2.5,
        mean_zscore=-2.0,
        points=6,
        restored_fraction=0.1,
        factors={"ndmi_trend": -0.08, "precipitation_sum": 4.0, "temperature_max": 35.0},
    )

    assessment = risk_module.assess(
        anomalies=[anomaly],
        recent_zscores=[(date(2024, 6, 20), -2.0)],
        observed_count=20,
        mean_valid_fraction=0.9,
        restored_fraction=0.1,
        climatology_available=True,
    )

    assert assessment.score == pytest.approx(sum(assessment.breakdown.values()), abs=0.01)
    assert assessment.status == FieldStatus.CRITICAL
    assert set(assessment.breakdown) == set(risk_module.WEIGHTS)


def test_phase_mismatch_halves_the_score_and_says_why() -> None:
    """Молча занижать риск нельзя: причина проговаривается пользователю."""
    common = {
        "start_date": date(2024, 6, 1),
        "end_date": date(2024, 6, 25),
        "duration_days": 25,
        "severity": AnomalySeverity.CRITICAL,
        "max_zscore": -2.5,
        "mean_zscore": -2.0,
        "points": 6,
        "restored_fraction": 0.0,
        "factors": {},
    }
    straight = anomalies_module.AnomalyPeriod(**common)
    rotated = anomalies_module.AnomalyPeriod(**common, phase_mismatch=True)

    arguments = {
        "recent_zscores": [(date(2024, 6, 20), -2.0)],
        "observed_count": 20,
        "mean_valid_fraction": 0.9,
        "restored_fraction": 0.0,
        "climatology_available": True,
    }
    without = risk_module.assess(anomalies=[straight], **arguments)
    with_mismatch = risk_module.assess(anomalies=[rotated], **arguments)

    assert with_mismatch.score == pytest.approx(without.score * 0.5, abs=0.01)
    assert with_mismatch.confidence < without.confidence
    assert any("севооборот" in line for line in with_mismatch.explanation)


def test_data_quality_affects_confidence_not_score() -> None:
    """Разрежённый ряд не делает поле здоровым — он делает вывод менее надёжным."""
    arguments = {
        "anomalies": [],
        "recent_zscores": [(date(2024, 6, 1), -1.0)],
        "observed_count": 20,
        "climatology_available": True,
    }
    clean = risk_module.assess(mean_valid_fraction=0.95, restored_fraction=0.0, **arguments)
    noisy = risk_module.assess(mean_valid_fraction=0.3, restored_fraction=0.8, **arguments)

    assert clean.score == noisy.score
    assert noisy.confidence < clean.confidence
