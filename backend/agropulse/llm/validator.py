"""Сверка сгенерированного текста с исходными данными.

Ключевая защита продукта. Модель получает готовые числа и обязана лишь
пересказать их, но языковая модель по природе способна округлить значение,
переставить цифры или уверенно назвать величину, которой ей не передавали.
В отчёте, который уходит руководителю хозяйства, это недопустимо.

Поэтому каждое число и каждая дата из текста ищутся в исходном JSON. Не нашлось —
текст бракуется целиком, а не правится: попытка починить отдельное число
означала бы, что мы доверяем остальному тексту без оснований.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Числа: целые и дробные, со знаком, с запятой или точкой в качестве разделителя.
NUMBER_PATTERN = re.compile(r"-?\d+(?:[.,]\d+)?")
# Даты в трёх написаниях: ISO, полном русском и коротком без года.
# Короткая форма обязательна: модель естественно пишет «с 13.05 по 05.06»,
# и без этого шаблона «13.05» разбиралось бы как число и браковало текст.
DATE_PATTERN = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b|\b\d{2}\.\d{2}\.\d{4}\b|\b\d{2}\.\d{2}\b"
)

# Числа, которые встречаются в обычной русской речи и не являются данными.
# Без этого списка бракуется каждый текст со словами «за 14 дней» или «на 100%».
ALLOWED_LITERALS = {
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
    12, 14, 20, 30, 50, 100,
    1000, 2020, 2021, 2022, 2023, 2024, 2025, 2026,
}

# Допуск при сравнении. Абсолютная часть покрывает округление малых величин
# вроде 0.8825 до 0.88; относительная нужна для крупных: температуру 21.24
# модель естественно округляет до 21.2, и фиксированного допуска тут мало.
ABSOLUTE_TOLERANCE = 0.011
RELATIVE_TOLERANCE = 0.01


def collect_numbers(payload: object) -> set[float]:
    """Собрать все числовые значения из структуры данных."""
    found: set[float] = set()

    def walk(node: object) -> None:
        if isinstance(node, bool):
            return
        if isinstance(node, int | float):
            found.add(float(node))
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list | tuple):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            # Числа, записанные строкой, тоже считаются известными.
            for match in NUMBER_PATTERN.findall(node):
                try:
                    found.add(float(match.replace(",", ".")))
                except ValueError:
                    continue

    walk(payload)
    return found


def collect_dates(payload: object) -> set[str]:
    """Собрать все даты из структуры данных в формате ISO."""
    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list | tuple):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            for match in DATE_PATTERN.findall(node):
                found.add(_normalize_date(match))
        elif hasattr(node, "isoformat"):
            found.add(node.isoformat()[:10])

    walk(payload)
    return found


def _normalize_date(value: str) -> str:
    """Привести дату к сопоставимому виду.

    Короткая форма без года сводится к «ММ-ДД»: год в ней не указан,
    и сравнивать его не с чем.
    """
    if "." in value:
        parts = value.split(".")
        if len(parts) == 3:
            day, month, year = parts
            return f"{year}-{month}-{day}"
        day, month = parts
        return f"{month}-{day}"
    return value


def _short_form(iso_date: str) -> str:
    """Короткая форма «ММ-ДД» для сопоставления дат без года."""
    return iso_date[5:10]


def _matches_known(value: float, known_numbers: set[float]) -> bool:
    """Проверить, соответствует ли число какому-либо известному значению.

    Сравнение ведётся по модулю. Причина в естественном языке: величину -2.25
    по-русски описывают как «отклонение достигло 2,25», знак уходит в слово
    «отклонение». Требовать совпадения знака означало бы браковать корректный
    текст. Защита от выдуманных величин при этом сохраняется: подставить
    произвольное число всё равно нельзя, оно обязано присутствовать в данных
    хотя бы по модулю.
    """
    for known in known_numbers:
        tolerance = max(ABSOLUTE_TOLERANCE, abs(known) * RELATIVE_TOLERANCE)
        if abs(abs(value) - abs(known)) <= tolerance:
            return True
    return False


def verify(text: str, payload: object) -> tuple[bool, list[str]]:
    """Проверить, что все числа и даты текста есть в исходных данных.

    Возвращает признак успеха и перечень нарушений для журнала.
    """
    known_numbers = collect_numbers(payload)
    known_dates = collect_dates(payload)
    # Компоненты дат: модель вправе написать «13 мая» вместо «2023-05-13»,
    # и число 13 в таком контексте не является выдуманным.
    for iso_date in known_dates:
        year, month, day = iso_date.split("-")
        known_numbers.update({float(year), float(month), float(day)})
    known_short = {_short_form(d) for d in known_dates}

    violations: list[str] = []

    for raw_date in DATE_PATTERN.findall(text):
        normalized = _normalize_date(raw_date)
        # Короткая форма сопоставляется отдельно: в ней нет года.
        known = normalized in known_dates or normalized in known_short
        if not known:
            violations.append(f"дата {raw_date} отсутствует в исходных данных")

    # Даты вырезаем из текста, иначе их составляющие попадут в проверку чисел.
    text_without_dates = DATE_PATTERN.sub(" ", text)

    for raw_number in NUMBER_PATTERN.findall(text_without_dates):
        try:
            value = float(raw_number.replace(",", "."))
        except ValueError:
            continue
        if value in ALLOWED_LITERALS:
            continue
        if not _matches_known(value, known_numbers):
            violations.append(f"число {raw_number} отсутствует в исходных данных")

    if violations:
        logger.warning("Текст забракован: %s", "; ".join(violations[:5]))
    return not violations, violations
