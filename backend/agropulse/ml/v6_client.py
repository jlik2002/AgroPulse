"""Клиент моделей на основе обученной V6.

Модель обучена заранее; здесь только предсказание по её артефактам —
см. `ml/v6/README.md`. Один и тот же клиент обслуживает и веб-сценарий,
и batch-режим `cli.py`: расхождение между ними означало бы, что проверяется
одно, а работает другое.

V6 восстанавливает пропуски и не прогнозирует вперёд. Прогноз считает
`ml/climatology_forecast.py`, и его источник отдаётся наружу отдельно,
чтобы в интерфейсе было видно, чем получено значение.
"""

from __future__ import annotations

import logging
from datetime import date
from functools import cached_property
from pathlib import Path

import numpy as np

from agropulse.ml import climatology_forecast
from agropulse.ml.client import (
    ForecastRequest,
    ForecastResult,
    ImputeRequest,
    ImputeResult,
    Prediction,
    SeriesPoint,
)
from agropulse.ml.v6 import pipeline

logger = logging.getLogger(__name__)

MODEL_VERSION = "ndvi-v6-native-anchor"

# Источник прогноза отличается от источника восстановления: V6 прогноза
# не делает вовсе, и выдавать климатический прогноз за неё нельзя.
FORECAST_SOURCE = "climatology"


class MissingReferenceDataset(RuntimeError):
    """Опорный набор не найден, а без него модель считать не может."""


class V6MLClient:
    """Восстановление пропусков моделью V6."""

    name = "v6"

    def __init__(self, artifacts_dir: Path, reference_dataset: Path | None = None) -> None:
        self._artifacts_dir = artifacts_dir
        self._reference_dataset = reference_dataset

    def is_available(self) -> bool:
        """Модель готова, если есть и её артефакты, и опорный набор.

        Опорный набор здесь не про точность, а про работоспособность.
        Признаки V6 межполевые: поле сравнивается с другими полями той же
        даты. Ряд, поданный в одиночку, сравнивать не с чем — расчёт
        обрывается, а не выдаёт приближение. Поэтому набор обязателен.
        """
        if not pipeline.Artifacts.stored_in(self._artifacts_dir):
            logger.error(
                "ml_v6_artifacts_missing",
                extra={"artifacts_dir": str(self._artifacts_dir)},
            )
            return False
        if self._reference_dataset is None or not self._reference_dataset.exists():
            logger.error(
                "ml_v6_reference_missing",
                extra={
                    "reason": "модели V6 нужен опорный набор задачи 1: её признаки "
                    "считаются относительно других полей, и без них расчёт невозможен",
                    "path": str(self._reference_dataset),
                    "setting": "ML_V6_REFERENCE_DATASET",
                },
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Восстановление пропусков
    # ------------------------------------------------------------------

    def impute(self, request: ImputeRequest) -> ImputeResult:
        return self.impute_batch([request])[0]

    def impute_batch(self, requests: list[ImputeRequest]) -> list[ImputeResult]:
        """Восстановить пропуски сразу по всем рядам.

        Батч здесь не оптимизация, а условие правильности: часть признаков
        V6 — межполевые (доноры, эффект дня, преобразование съёмки). Поле,
        посчитанное в одиночку, увидит их пустыми. Поэтому все ряды запроса
        попадают в один кадр и считаются вместе.
        """
        rows, wanted = self._rows(requests)
        if not rows:
            return [_empty(request) for request in requests]

        frame = pipeline.combine(self._reference, pipeline.frame_from_rows(rows))
        target_ids = frame.loc[
            frame.is_synthetic_gap.fillna(False) & (frame.split == "test"), "row_id"
        ].to_numpy()

        logger.info(
            "V6: рядов %s, целевых точек %s, контекст %s строк",
            len(requests), len(target_ids), len(frame),
        )
        values, target_rows = pipeline.predict(frame, self._artifacts, target_ids)

        restored = {
            (str(polygon), day): float(value)
            for polygon, day, value in zip(
                target_rows.polygon, target_rows.date_str, values, strict=True
            )
        }
        return [
            self._result(request, targets, restored)
            for request, targets in zip(requests, wanted, strict=True)
        ]

    def _rows(self, requests: list[ImputeRequest]) -> tuple[list[dict], list[set[date]]]:
        """Разложить запросы в строки кадра наблюдений.

        Целевая дата, которой нет среди наблюдений, добавляется отдельной
        строкой: в веб-сценарии восстанавливается сплошная суточная сетка,
        и в дни без пролёта спутника наблюдения нет вовсе.
        """
        rows: list[dict] = []
        wanted: list[set[date]] = []
        for request in requests:
            targets = set(request.targets)
            wanted.append(targets)
            seen: set[date] = set()
            for point in request.observations:
                seen.add(point.date)
                rows.append(
                    self._row(
                        request,
                        point.date,
                        point.primary_ndvi,
                        point.features,
                        point.date in targets,
                    )
                )
            for day in sorted(targets - seen):
                rows.append(self._row(request, day, None, {}, True))
        return rows, wanted

    @staticmethod
    def _row(
        request: ImputeRequest,
        day: date,
        value: float | None,
        features: dict[str, float | None],
        is_target: bool,
    ) -> dict:
        """Строка в схеме задачи 1.

        Признаки наблюдения передаются как есть: в batch-режиме это колонки
        исходного набора (`s2_ndvi`, `era5_temp_c` и прочие), и модель ждёт
        именно их. Целевая строка маскируется целиком уже внутри модели —
        скрыт не только NDVI, но и индексы с погодой той же даты.
        """
        row: dict = {name: item for name, item in features.items() if name not in _RESERVED}
        row.update(
            anon_polygon_id=request.polygon_id,
            date=day.isoformat(),
            primary_ndvi=None if is_target else value,
            crop_type=request.crop_type,
            is_synthetic_gap=is_target,
        )
        # Ряд без колонок приборов приходит из веб-сценария, где источник —
        # Sentinel-2. Без этого прибор не определится, и значение будет
        # считано в шкале Landsat, которая на 0.037 ниже.
        if value is not None and not is_target and not _has_sensor(features):
            row["s2_ndvi"] = value
        return row

    def _result(
        self,
        request: ImputeRequest,
        targets: set[date],
        restored: dict[tuple[str, date], float],
    ) -> ImputeResult:
        predictions = []
        for day in sorted(targets):
            value = restored.get((request.polygon_id, day.isoformat()))
            if value is None or not np.isfinite(value):
                continue
            predictions.append(Prediction(date=day, value=round(value, 6), confidence=None))
        return ImputeResult(
            predictions=predictions, model_version=MODEL_VERSION, source=self.name
        )

    # ------------------------------------------------------------------
    # Прогноз
    # ------------------------------------------------------------------

    def forecast(self, request: ForecastRequest) -> ForecastResult:
        """Прогноз вперёд. V6 этого не умеет — считает климатический метод."""
        return climatology_forecast.forecast(
            request, model_version=MODEL_VERSION, source=FORECAST_SOURCE
        )

    # ------------------------------------------------------------------

    @cached_property
    def _artifacts(self) -> pipeline.Artifacts:
        logger.info("V6: загрузка модели из %s", self._artifacts_dir)
        return pipeline.Artifacts.load(self._artifacts_dir)

    @cached_property
    def _reference(self):
        """Опорный набор — контекст, в котором модель обучалась.

        Межполевые признаки считаются относительно тех же полей, что были
        при обучении, поэтому набор нужен и при предсказании.
        """
        if self._reference_dataset is None or not self._reference_dataset.exists():
            raise MissingReferenceDataset(
                "модели V6 нужен опорный набор задачи 1, путь задаётся "
                f"настройкой ML_V6_REFERENCE_DATASET (сейчас: {self._reference_dataset})"
            )
        logger.info("V6: опорный набор %s", self._reference_dataset)
        return pipeline.load_frame(self._reference_dataset)


# Ключевые колонки задаются самим запросом; одноимённый признак их не заменяет.
_RESERVED = frozenset(
    {"anon_polygon_id", "date", "primary_ndvi", "crop_type", "is_synthetic_gap"}
)

_SENSOR_HINTS = frozenset({"s2_ndvi", "landsat_ndvi", "modis_ndvi"})


def _has_sensor(features: dict[str, float | None]) -> bool:
    return any(features.get(name) is not None for name in _SENSOR_HINTS)


def _empty(request: ImputeRequest) -> ImputeResult:
    return ImputeResult(predictions=[], model_version=MODEL_VERSION, source=V6MLClient.name)


__all__ = ["V6MLClient", "MODEL_VERSION", "SeriesPoint"]
