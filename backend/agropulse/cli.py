"""Технический batch-инференс.

Вторая обязательная точка запуска по постановке задачи: принимает
`private_features.csv` и формирует `submission.csv` со значениями
`primary_ndvi` для строк, помеченных `is_synthetic_gap = True`.

Восстановление выполняет тот же клиент моделей, что и веб-сервис
(`ml/resolve.py`), а признаки строит тот же модуль `features/contract`.
Разделять эти пути нельзя: расхождение между batch-режимом и веб-сценарием
означало бы, что проверяется одно, а работает другое.

Использование:

    python -m agropulse.cli predict --input private_features.csv --output submission.csv
    python -m agropulse.cli validate --input private_features.csv --submission submission.csv
"""

from __future__ import annotations

import argparse
import csv
import logging
import math
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from agropulse.ml.client import ImputeRequest, SeriesPoint
from agropulse.ml.resolve import get_client

logger = logging.getLogger(__name__)

COLUMN_POLYGON = "anon_polygon_id"
COLUMN_DATE = "date"
COLUMN_TARGET = "primary_ndvi"
COLUMN_FLAG = "is_synthetic_gap"
COLUMN_PREDICTION = "primary_ndvi_pred"

SUBMISSION_HEADER = [COLUMN_POLYGON, COLUMN_DATE, COLUMN_PREDICTION]

TRUE_VALUES = {"true", "1", "yes", "t"}


def _is_true(value: str | None) -> bool:
    return (value or "").strip().lower() in TRUE_VALUES


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return None if math.isnan(number) else number


def read_features(path: Path) -> tuple[dict[str, list[dict]], list[tuple[str, date]]]:
    """Прочитать тестовый набор.

    Возвращает наблюдения, сгруппированные по полигону, и перечень контрольных
    точек — тех строк, для которых требуется предсказание.
    """
    by_polygon: dict[str, list[dict]] = defaultdict(list)
    targets: list[tuple[str, date]] = []

    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = {COLUMN_POLYGON, COLUMN_DATE} - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"во входном файле нет обязательных колонок: {', '.join(missing)}")

        for row in reader:
            polygon = (row.get(COLUMN_POLYGON) or "").strip()
            raw_date = (row.get(COLUMN_DATE) or "").strip()
            if not polygon or not raw_date:
                continue
            try:
                day = date.fromisoformat(raw_date)
            except ValueError:
                logger.warning("Строка с некорректной датой пропущена: %s", raw_date)
                continue

            is_gap = _is_true(row.get(COLUMN_FLAG))
            by_polygon[polygon].append(
                {
                    "date": day,
                    # У контрольной строки целевое значение скрыто, поэтому
                    # даже при наличии колонки оно не должно попасть в модель.
                    "ndvi": None if is_gap else _to_float(row.get(COLUMN_TARGET)),
                    "row": row,
                }
            )
            if is_gap:
                targets.append((polygon, day))

    for rows in by_polygon.values():
        rows.sort(key=lambda item: item["date"])
    return by_polygon, targets


def predict(input_path: Path, output_path: Path) -> int:
    """Сформировать submission.csv."""
    by_polygon, targets = read_features(input_path)
    if not targets:
        raise SystemExit(
            f"в файле нет строк с {COLUMN_FLAG} = True — предсказывать нечего"
        )

    targets_by_polygon: dict[str, list[date]] = defaultdict(list)
    for polygon, day in targets:
        targets_by_polygon[polygon].append(day)

    client = get_client()
    logger.info(
        "Полигонов: %s, контрольных точек: %s, клиент: %s",
        len(by_polygon), len(targets), client.name,
    )

    predictions: dict[tuple[str, date], float] = {}
    for polygon, rows in by_polygon.items():
        wanted = targets_by_polygon.get(polygon)
        if not wanted:
            continue
        result = client.impute(
            ImputeRequest(
                polygon_id=polygon,
                observations=[
                    SeriesPoint(date=row["date"], primary_ndvi=row["ndvi"]) for row in rows
                ],
                targets=sorted(wanted),
            )
        )
        for item in result.predictions:
            predictions[(polygon, item.date)] = item.value

    # Пропуски в submission не допускаются: на каждую контрольную точку должна
    # быть строка. Там, где модель отказалась предсказывать, подставляем
    # медиану известных значений полигона, а при их отсутствии — общую медиану.
    filled = _fill_missing(by_polygon, targets, predictions)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(SUBMISSION_HEADER)
        for polygon, day in targets:
            writer.writerow([polygon, day.isoformat(), f"{filled[(polygon, day)]:.6f}"])

    logger.info("Записано %s строк в %s", len(targets), output_path)
    return len(targets)


def _fill_missing(
    by_polygon: dict[str, list[dict]],
    targets: list[tuple[str, date]],
    predictions: dict[tuple[str, date], float],
) -> dict[tuple[str, date], float]:
    """Заполнить точки, для которых предсказание не получено."""
    import statistics

    all_known = [
        row["ndvi"] for rows in by_polygon.values() for row in rows if row["ndvi"] is not None
    ]
    global_median = statistics.median(all_known) if all_known else 0.0

    per_polygon_median: dict[str, float] = {}
    for polygon, rows in by_polygon.items():
        known = [row["ndvi"] for row in rows if row["ndvi"] is not None]
        per_polygon_median[polygon] = statistics.median(known) if known else global_median

    filled = dict(predictions)
    fallbacks = 0
    for key in targets:
        if key not in filled:
            filled[key] = per_polygon_median[key[0]]
            fallbacks += 1
    if fallbacks:
        logger.warning(
            "Для %s точек предсказание не получено, подставлена медиана полигона", fallbacks
        )
    return filled


def validate(input_path: Path, submission_path: Path) -> bool:
    """Проверить submission.csv на соответствие требованиям платформы.

    Требования: ровно одна строка на пару `anon_polygon_id` + `date`, только
    контрольные точки, без пропусков и NaN, кодировка UTF-8, разделитель запятая.
    """
    _, targets = read_features(input_path)
    expected = set(targets)

    problems: list[str] = []
    seen: set[tuple[str, date]] = set()

    with submission_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != SUBMISSION_HEADER:
            problems.append(
                f"заголовок {reader.fieldnames} вместо {SUBMISSION_HEADER}"
            )
        for number, row in enumerate(reader, start=2):
            polygon = (row.get(COLUMN_POLYGON) or "").strip()
            try:
                day = date.fromisoformat((row.get(COLUMN_DATE) or "").strip())
            except ValueError:
                problems.append(f"строка {number}: некорректная дата")
                continue

            key = (polygon, day)
            if key in seen:
                problems.append(f"строка {number}: пара {polygon} + {day} встречается повторно")
            seen.add(key)

            if key not in expected:
                problems.append(f"строка {number}: {polygon} + {day} не является контрольной точкой")

            value = _to_float(row.get(COLUMN_PREDICTION))
            if value is None:
                problems.append(f"строка {number}: пустое или нечисловое значение")

    for key in expected - seen:
        problems.append(f"нет предсказания для {key[0]} + {key[1]}")

    if problems:
        print(f"Найдено проблем: {len(problems)}")
        for problem in problems[:20]:
            print(f"  • {problem}")
        if len(problems) > 20:
            print(f"  … и ещё {len(problems) - 20}")
        return False

    print(f"submission.csv корректен: {len(seen)} строк, все контрольные точки покрыты")
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(prog="agropulse", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    predict_parser = commands.add_parser("predict", help="сформировать submission.csv")
    predict_parser.add_argument("--input", type=Path, required=True)
    predict_parser.add_argument("--output", type=Path, default=Path("submission.csv"))

    validate_parser = commands.add_parser("validate", help="проверить формат submission.csv")
    validate_parser.add_argument("--input", type=Path, required=True)
    validate_parser.add_argument("--submission", type=Path, default=Path("submission.csv"))

    arguments = parser.parse_args()

    if arguments.command == "predict":
        count = predict(arguments.input, arguments.output)
        print(f"Готово: {count} строк в {arguments.output}")
    elif arguments.command == "validate":
        sys.exit(0 if validate(arguments.input, arguments.submission) else 1)


if __name__ == "__main__":
    main()
