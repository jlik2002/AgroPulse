"""Индекс потребности хозяйства в поддержке.

Проверяются два способа, которыми средневзвешенная оценка врёт, и граница,
за которой заключение не выдаётся. Остальное — арифметика, которая ломается
вместе с этими тремя случаями.
"""

from __future__ import annotations

from agropulse.analytics.farm import FarmTrust, FieldInput, ReviewCategory, assess
from agropulse.db.models import FieldStatus


def _field(area: float, status: FieldStatus, score: float | None, confidence=0.7) -> FieldInput:
    return FieldInput(
        area_ha=area, status=status, risk_score=score, confidence=confidence
    )


def test_single_critical_field_does_not_dissolve_in_area() -> None:
    """Одно критическое поле на большом хозяйстве обязано остаться видимым.

    Средневзвешенное по площади размывает его до пары баллов: 20 га с баллом 85
    против 800 га нормы дают вклад около двух. Поэтому итог не опускается ниже
    доли максимального балла отдельного поля.
    """
    result = assess(
        [
            _field(20.0, FieldStatus.CRITICAL, 85.0),
            _field(800.0, FieldStatus.NORMAL, 5.0),
        ]
    )

    assert result.weighted_risk is not None and result.weighted_risk < 10
    assert result.support_need_score is not None and result.support_need_score >= 50
    assert result.category is ReviewCategory.SUPPORT


def test_field_without_data_lowers_trust_not_score() -> None:
    """Поле без наблюдений не занижает балл, но понижает достоверность.

    Иначе хозяйство, по которому нечего сказать, окажется внизу реестра —
    то есть система заявит «поддержка не нужна» там, где просто ничего
    не увидела.
    """
    result = assess(
        [
            _field(100.0, FieldStatus.CRITICAL, 80.0),
            _field(100.0, FieldStatus.INSUFFICIENT_DATA, None),
        ]
    )

    # В средневзвешенное вошло только оценённое поле.
    assert result.weighted_risk == 80.0
    assert result.assessed_area_ha == 100.0
    assert result.unassessed_area_ha == 100.0
    assert result.trust is not FarmTrust.HIGH


def test_farm_without_conclusion_is_not_ranked() -> None:
    """Оценено меньше половины площади — заключения нет, а не низкий приоритет."""
    result = assess(
        [
            _field(50.0, FieldStatus.NORMAL, 10.0),
            _field(200.0, FieldStatus.INSUFFICIENT_DATA, None),
        ]
    )

    assert result.category is ReviewCategory.UNDETERMINED
    assert result.trust is FarmTrust.LOW
    assert result.notes


def test_farm_without_fields_is_not_an_error() -> None:
    """Хозяйство заводят до того, как рисуют контуры."""
    result = assess([])

    assert result.support_need_score is None
    assert result.category is ReviewCategory.UNDETERMINED
