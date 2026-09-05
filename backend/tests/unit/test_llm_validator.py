"""Сверка сгенерированного текста с исходными данными.

Ключевая защита продукта: в отчёте, который уходит руководителю хозяйства,
выдуманное число недопустимо. Тесты закрепляют обе стороны баланса — текст
с придуманной величиной бракуется, а корректный текст на естественном русском
не бракуется из-за формы записи.
"""

from __future__ import annotations

from agropulse.llm import validator

PAYLOAD = {
    "field_name": "Поле №3",
    "risk_score": 72.5,
    "anomalies": [
        {
            "start_date": "2024-05-13",
            "end_date": "2024-06-05",
            "duration_days": 24,
            "max_zscore": -2.25,
            "factors": {"temperature_max": 21.24},
        }
    ],
}


def test_text_without_numbers_passes() -> None:
    ok, violations = validator.verify(
        "Поле почти месяц развивалось хуже обычного. Требуется осмотр.", PAYLOAD
    )

    assert ok is True
    assert violations == []


def test_invented_number_is_rejected() -> None:
    ok, violations = validator.verify("Балл риска составил 88,3.", PAYLOAD)

    assert ok is False
    assert violations


def test_invented_date_is_rejected() -> None:
    ok, violations = validator.verify("Отклонение началось 2023-01-09.", PAYLOAD)

    assert ok is False
    assert any("дата" in violation for violation in violations)


def test_known_number_passes() -> None:
    ok, _ = validator.verify("Балл риска — 72,5.", PAYLOAD)

    assert ok is True


def test_rounding_is_tolerated() -> None:
    """Модель естественно округляет 21.24 до 21.2 — это не выдумка."""
    ok, _ = validator.verify("Максимальная температура достигала 21,2 градуса.", PAYLOAD)

    assert ok is True


def test_sign_is_allowed_to_move_into_words() -> None:
    """«Отклонение достигло 2,25» — корректная русская фраза для -2.25."""
    ok, _ = validator.verify("Отклонение достигло 2,25.", PAYLOAD)

    assert ok is True


def test_short_date_form_is_understood() -> None:
    """Модель пишет «с 13.05 по 05.06» — эта форма обязана распознаваться."""
    ok, violations = validator.verify("Спад держался с 13.05 по 05.06.", PAYLOAD)

    assert ok is True, violations


def test_date_components_are_not_treated_as_invented_numbers() -> None:
    """«13 мая» — это дата из данных, а не выдуманное число 13."""
    ok, violations = validator.verify("Спад начался 13 мая и держался до 5 июня.", PAYLOAD)

    assert ok is True, violations


def test_common_speech_numbers_are_allowed() -> None:
    """Без списка допустимых литералов бракуется каждый текст со словом «14 дней»."""
    ok, _ = validator.verify("Прогноз построен на 14 дней вперёд.", PAYLOAD)

    assert ok is True


def test_numbers_are_collected_from_nested_structures() -> None:
    numbers = validator.collect_numbers(PAYLOAD)

    assert 72.5 in numbers
    assert -2.25 in numbers
    assert 21.24 in numbers


def test_dates_are_collected_in_iso_form() -> None:
    dates = validator.collect_dates(PAYLOAD)

    assert "2024-05-13" in dates
    assert "2024-06-05" in dates
