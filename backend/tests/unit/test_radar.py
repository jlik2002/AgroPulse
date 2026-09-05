"""Радарный ряд Sentinel-1: производные величины, события, подтверждённость.

Проверяются продуктовые правила, а не формулы. Главное из них — радар нельзя
сравнивать между разными орбитами: угол падения луча меняется, и разность
уровней превращается в выдуманное событие на поле. Остальные правила того же
рода: радар не ставит диагноз, а перечисляет гипотезы; подтверждённость растёт
только тогда, когда источники действительно сошлись.
"""

from __future__ import annotations

from datetime import date, timedelta

from agropulse.analytics import radar as radar_module
from agropulse.analytics.radar import RadarSample
from agropulse.providers.radar_gee import _aggregate_by_date

START = date(2026, 5, 1)


def _sample(offset: int, vh: float, vv: float = -11.0, orbit: int = 43) -> RadarSample:
    return RadarSample(
        date=START + timedelta(days=offset),
        orbit_direction="descending",
        relative_orbit=orbit,
        vv_median_db=vv,
        vh_median_db=vh,
        rvi_median=0.4,
    )


# ---------------------------------------------------------------------------
# Производные величины
# ---------------------------------------------------------------------------


def test_difference_is_not_taken_across_orbits() -> None:
    """Смена орбиты — не событие на поле, а другая геометрия съёмки.

    Самая частая ошибка при работе с Sentinel-1: посчитать разность между
    соседними по времени снимками разных пролётов и увидеть скачок в несколько
    децибел там, где на поле ничего не произошло.
    """
    samples = [
        _sample(0, vh=-18.0, orbit=43),
        # Следующий день, другая орбита и заметно другой уровень сигнала.
        _sample(1, vh=-12.0, orbit=116),
        _sample(12, vh=-18.2, orbit=43),
    ]

    derived = radar_module.derive(samples)

    # У снимка чужой орбиты разности нет вовсе: сравнивать его не с чем.
    assert START + timedelta(days=1) not in derived
    # А внутри своей орбиты разность посчитана и она мала.
    assert derived[START + timedelta(days=12)]["vh_change_db"] == -0.2


def test_difference_is_not_taken_across_a_long_gap() -> None:
    """Разрыв в ряду — это пропуск, а не изменение за один шаг."""
    samples = [_sample(0, vh=-18.0), _sample(60, vh=-13.0)]

    derived = radar_module.derive(samples)

    assert derived == {}


def test_change_point_score_needs_enough_history() -> None:
    """Резкость перехода измеряется рангом в истории поля.

    На трёх точках ранг не значит ничего, поэтому оценка не выставляется:
    отсутствие числа честнее выдуманного.
    """
    short = radar_module.derive([_sample(index * 12, vh=-18.0) for index in range(3)])
    assert all("change_point_score" not in values for values in short.values())

    long_series = radar_module.derive(
        [_sample(index * 12, vh=-18.0 - index * 0.1) for index in range(12)]
    )
    assert any("change_point_score" in values for values in long_series.values())


# ---------------------------------------------------------------------------
# События
# ---------------------------------------------------------------------------


def test_vegetation_drop_is_reported_as_hypotheses_not_a_diagnosis() -> None:
    """Падение сигнала растительности одинаково выглядит при уборке,
    полегании и завершении вегетации. Выбор между ними радару недоступен."""
    samples = [_sample(0, vh=-15.0), _sample(12, vh=-19.0)]
    derived = radar_module.derive(samples)

    events = radar_module.detect_events(samples, derived)

    assert len(events) == 1
    event = events[0]
    assert event.kind == "vegetation_drop"
    assert event.magnitude_db == -4.0
    assert len(event.hypotheses) > 1
    assert "уборка или скашивание" in event.hypotheses


def test_surface_change_is_separated_from_vegetation() -> None:
    """Сдвиг сигнала почвы при неизменном сигнале растительности — это
    состояние поверхности, а не растительности."""
    samples = [
        _sample(0, vh=-18.0, vv=-13.5),
        _sample(12, vh=-18.1, vv=-10.0),
    ]
    derived = radar_module.derive(samples)

    events = radar_module.detect_events(samples, derived)

    assert [event.kind for event in events] == ["surface_change"]
    assert "увлажнение после осадков или полива" in events[0].hypotheses


def test_small_fluctuation_is_not_an_event() -> None:
    """Колебание в пределах спекла событием не является."""
    samples = [_sample(0, vh=-18.0), _sample(12, vh=-18.4)]

    events = radar_module.detect_events(samples, radar_module.derive(samples))

    assert events == []


# ---------------------------------------------------------------------------
# Вердикт радара
# ---------------------------------------------------------------------------


def test_radar_verdict_separates_silence_from_absence() -> None:
    """Низкий уровень доверия получается по двум разным причинам, и путать
    их нельзя.

    «Снимки в окне есть, изменений не видно» — свидетельство против события.
    «Снимков нет» — не свидетельство вообще: радарного покрытия не хватает
    независимо от того, что происходило на поле.
    """
    window = dict(start_date=date(2026, 7, 1), end_date=date(2026, 7, 20), events=[])

    silent = [
        RadarSample(date=date(2026, 7, 4), orbit_direction="descending",
                    relative_orbit=43, vh_median_db=-18.0),
        RadarSample(date=date(2026, 7, 16), orbit_direction="descending",
                    relative_orbit=43, vh_median_db=-18.1),
    ]
    assert radar_module.verdict(samples=silent, **window) == radar_module.RADAR_SILENT

    assert radar_module.verdict(samples=[], **window) == radar_module.RADAR_NO_DATA

    dropping = [
        silent[0],
        RadarSample(date=date(2026, 7, 16), orbit_direction="descending",
                    relative_orbit=43, vh_median_db=-22.0),
    ]
    assert radar_module.verdict(samples=dropping, **window) == radar_module.RADAR_AGREES


def test_radar_event_inside_the_window_is_confirmation() -> None:
    """Уровень сигнала может остаться в норме, а структура — резко просесть
    именно в дни события. Это тоже подтверждение, и терять его нельзя."""
    flat = [
        RadarSample(date=date(2026, 7, 2) + timedelta(days=index * 12),
                    orbit_direction="descending", relative_orbit=43, vh_median_db=-18.0)
        for index in range(2)
    ]
    drop = radar_module.RadarEvent(
        date=date(2026, 7, 9), kind="vegetation_drop", magnitude_db=-4.2, score=0.9,
        title="Резкое снижение радарного сигнала растительности", confirmed=True,
    )

    assert radar_module.verdict(
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 20),
        samples=flat, events=[drop],
    ) == radar_module.RADAR_AGREES


def test_unconfirmed_radar_event_is_not_confirmation() -> None:
    """Скачок, удержание которого проверить нечем, подтверждением не является."""
    flat = [
        RadarSample(date=date(2026, 7, 2) + timedelta(days=index * 12),
                    orbit_direction="descending", relative_orbit=43, vh_median_db=-18.0)
        for index in range(2)
    ]
    unconfirmed = radar_module.RadarEvent(
        date=date(2026, 7, 9), kind="vegetation_drop", magnitude_db=-4.2, score=0.9,
        title="Резкое снижение радарного сигнала растительности", confirmed=False,
    )

    assert radar_module.verdict(
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 20),
        samples=flat, events=[unconfirmed],
    ) == radar_module.RADAR_SILENT


# ---------------------------------------------------------------------------
# Сведение сцен к дате
# ---------------------------------------------------------------------------


def test_two_passes_on_one_date_do_not_get_averaged() -> None:
    """Восходящий и нисходящий пролёты в один день усреднять нельзя: среднее
    не соответствует ни одной реальной геометрии съёмки. Побеждает пролёт
    с большим покрытием."""
    raw = [
        {
            "date": "2026-06-14", "scene_id": "asc", "orbit_direction": "ASCENDING",
            "relative_orbit": 116, "vv": -8.0, "vh": -14.0, "rvi": 0.5,
            "vv_p25": -9.0, "vv_p75": -7.0, "valid_fraction": 0.6,
            "low_signal_fraction": 0.1,
        },
        {
            "date": "2026-06-14", "scene_id": "desc", "orbit_direction": "DESCENDING",
            "relative_orbit": 43, "vv": -12.0, "vh": -18.0, "rvi": 0.4,
            "vv_p25": -13.0, "vv_p75": -11.0, "valid_fraction": 0.98,
            "low_signal_fraction": 0.2,
        },
    ]

    result = _aggregate_by_date(raw, source="s1_gee")

    assert len(result) == 1
    observation = result[0]
    assert observation.orbit_direction == "descending"
    assert observation.vv_median_db == -12.0
    assert observation.scene_id == "desc"


def test_partial_coverage_becomes_a_gap_with_a_reason() -> None:
    """Поле на краю полосы съёмки — это пропуск с объяснением, а не
    посчитанное по случайному куску контура значение."""
    raw = [
        {
            "date": "2026-06-14", "scene_id": "edge", "orbit_direction": "DESCENDING",
            "relative_orbit": 43, "vv": -12.0, "vh": -18.0, "rvi": 0.4,
            "vv_p25": -13.0, "vv_p75": -11.0, "valid_fraction": 0.2,
            "low_signal_fraction": 0.2,
        }
    ]

    observation = _aggregate_by_date(raw, source="s1_gee")[0]

    assert observation.vh_median_db is None
    assert observation.missing_reason is not None
    assert "20%" in observation.missing_reason


def test_scene_without_data_over_the_field_is_dropped() -> None:
    """Рамка снимка шире полосы съёмки, и поле может оказаться за её краем.

    Такая сцена — не пропуск в ряду, а чужой снимок: показывать по ней дату
    с объяснением «покрытие 0%» значит засорять ряд теми пролётами, которые
    поля вообще не касались.
    """
    raw = [
        {
            "date": "2019-01-04", "scene_id": "outside", "orbit_direction": "DESCENDING",
            "relative_orbit": 21, "vv": None, "vh": None, "rvi": None,
            "vv_p25": None, "vv_p75": None, "valid_fraction": 0.0,
            "low_signal_fraction": None,
        }
    ]

    assert _aggregate_by_date(raw, source="s1_gee") == []


def test_slices_of_one_pass_are_merged_by_coverage() -> None:
    """Срез, зацепивший поле краем, не должен весить столько же, сколько
    накрывший его целиком."""
    raw = [
        {
            "date": "2026-06-14", "scene_id": "a", "orbit_direction": "DESCENDING",
            "relative_orbit": 43, "vv": -20.0, "vh": -18.0, "rvi": 0.4,
            "vv_p25": -21.0, "vv_p75": -19.0, "valid_fraction": 0.1,
            "low_signal_fraction": 0.2,
        },
        {
            "date": "2026-06-14", "scene_id": "b", "orbit_direction": "DESCENDING",
            "relative_orbit": 43, "vv": -10.0, "vh": -18.0, "rvi": 0.4,
            "vv_p25": -11.0, "vv_p75": -9.0, "valid_fraction": 0.9,
            "low_signal_fraction": 0.2,
        },
    ]

    observation = _aggregate_by_date(raw, source="s1_gee")[0]

    # Среднее было бы -15; с весом по покрытию значение тянется к полному срезу.
    assert observation.vv_median_db == -11.0
