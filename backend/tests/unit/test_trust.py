"""Вердикт о доверии к событию.

Проверяются правила, ради которых прежняя модель и была переписана. Все они
об одном: доверие должно падать от свидетельств против события, а не от
пробелов в наших данных.
"""

from __future__ import annotations

from agropulse.analytics import trust as trust_module
from agropulse.analytics.radar import RADAR_AGREES, RADAR_NO_DATA, RADAR_SILENT


def _assess(**overrides):
    defaults = dict(
        observations=3,
        coverage=0.9,
        radar=RADAR_NO_DATA,
        weather_explains=False,
        phase_mismatch=False,
    )
    return trust_module.assess(**{**defaults, **overrides})


def test_one_fact_is_charged_once() -> None:
    """Облачное окно — это и есть мера слабости оптики, а не добавка к ней.

    Прежняя модель списывала его трижды: понижением веса оптики, потерей
    балла за устойчивость и отдельным штрафом. Событие, на котором сошлись
    радар и погода, получало вердикт «слабое» — то есть сервис не верил
    собственной находке из-за облаков, которые ровно поэтому и не мешают
    радару.
    """
    cloudy_but_corroborated = _assess(
        observations=1, coverage=0.2, radar=RADAR_AGREES, weather_explains=True
    )

    assert cloudy_but_corroborated.level == trust_module.TRUST_CONFIRMED


def test_missing_radar_does_not_lower_trust() -> None:
    """Отсутствие свидетельства — не свидетельство против.

    Радарного покрытия не хватает независимо от того, что происходило
    на поле, и наказывать за это вывод значит наказывать его за пробелы
    в чужом каталоге.
    """
    assert _assess(observations=4, radar=RADAR_NO_DATA).level == trust_module.TRUST_CONFIRMED


def test_silent_radar_does_not_overturn_measured_optics() -> None:
    """Радар видит структуру полога, оптика — состояние листа.

    Хлороз и азотное голодание меняют цвет, не меняя структуру, поэтому
    у надёжно измеренного оптического события молчащий радар означает
    «ухудшение спектральное», а не «события не было».
    """
    result = _assess(observations=4, coverage=0.9, radar=RADAR_SILENT)

    assert result.level == trust_module.TRUST_CONFIRMED
    assert any("спектральным" in reason for reason in result.reasons)


def test_silent_radar_disputes_weak_optics() -> None:
    """Единственный настоящий минус: оптика слаба, а независимый источник,
    у которого данные есть, события не подтверждает."""
    assert _assess(observations=1, radar=RADAR_SILENT).level == trust_module.TRUST_DISPUTED


def test_event_without_a_single_real_image_is_not_confirmed_by_itself() -> None:
    """Событие, целиком выведенное расчётом, само себя подтвердить не может."""
    result = _assess(observations=0, coverage=None, radar=RADAR_NO_DATA)

    assert result.level == trust_module.TRUST_UNVERIFIED
    assert result.optical == trust_module.OPTICAL_NONE

    # Но если его независимо видит радар — это уже событие под облаками,
    # а не артефакт восстановления.
    assert _assess(observations=0, radar=RADAR_AGREES).level == trust_module.TRUST_CONFIRMED


def test_phase_mismatch_blocks_confirmation() -> None:
    """Несовпадение фазы сезона бьёт по основанию сравнения: норма построена
    по годам, когда на поле могла расти другая культура.

    Прежде это вдвое резало число, и причина оставалась невидимой.
    """
    result = _assess(observations=5, radar=RADAR_AGREES, phase_mismatch=True)

    assert result.level == trust_module.TRUST_UNVERIFIED
    assert any("смена культуры" in reason for reason in result.reasons)


def test_half_covered_images_are_weak_evidence() -> None:
    """Два снимка, наполовину закрытые облаком, — не то же самое,
    что два чистых."""
    assert _assess(observations=2, coverage=0.9).optical == trust_module.OPTICAL_STRONG
    assert _assess(observations=2, coverage=0.2).optical == trust_module.OPTICAL_WEAK


def test_verdict_always_carries_its_reasons() -> None:
    """Вердикт без причин — ещё один непонятный ярлык на экране."""
    for radar in (RADAR_AGREES, RADAR_SILENT, RADAR_NO_DATA):
        for observations in (0, 1, 4):
            result = _assess(observations=observations, radar=radar)
            assert result.reasons, (radar, observations)
            assert result.level in {
                trust_module.TRUST_CONFIRMED,
                trust_module.TRUST_UNVERIFIED,
                trust_module.TRUST_DISPUTED,
            }
