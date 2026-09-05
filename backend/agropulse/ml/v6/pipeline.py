"""Движок модели V6: предсказание по обученной модели.

Оригинальный `ndvi_v6.py` из архива экспериментов обучал модель и сразу же
предсказывал одним проходом. Обучение занимает около пяти минут, и в сервисе
ему делать нечего: модель обучена один раз, её артефакты лежат в `artifacts/`,
здесь остаётся только предсказание. Код обучения сохранён в архиве
экспериментов вместе с командой запуска — см. README.md пакета.

Разделение обучения и предсказания законно и не меняет результат. Признаки
строятся построчно: `sensor_features` и `scene_features` берут из `base`
только перечень строк, для которых считать, а всю статистику — из `visible`.
Значение признака строки не зависит от того, какие ещё строки попали в тот же
вызов. Равенство проверяется тестом на эталонном submission.

Модель предсказывает не сам NDVI, а поправку к опоре `native_anchor` —
линейной интерполяции в шкале конкретного прибора. Деревья плохо выражают
тождество `y ≈ x`, поэтому опора считается арифметикой, а обучение достаётся
только остатку. Предсказания трёх приборов сворачиваются вероятностями
классификатора, который угадывает, каким прибором снята целевая дата.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, CatBoostRegressor

from agropulse.ml.v6 import ndvi_v3 as v3
from agropulse.ml.v6 import ndvi_v5 as v5
from agropulse.ml.v6.scene_features import scene_features

logger = logging.getLogger(__name__)

# Опора, выбранная по результатам сравнения вариантов V6 (см. README пакета).
ANCHOR = "native_anchor"

# Организаторы оценивают NDVI; значения вне этого диапазона физически
# невозможны и означали бы промах модели, а не состояние поля.
PREDICTION_RANGE = (-0.1, 1.0)

# Колонки приборов нужны модели всегда: по ним собираются матрицы доноров
# и определяется, каким прибором снята дата. У живого поля их может не быть.
SENSOR_COLUMNS = (
    "s2_ndvi", "s2_evi", "s2_ndwi",
    "landsat_ndvi", "landsat_evi", "landsat_ndwi",
    "modis_ndvi", "modis_evi",
)

CLASSIFIER_FILE = "classifier.cbm"
REGRESSOR_FILE = f"{ANCHOR}.cbm"


@dataclass(frozen=True, slots=True)
class Artifacts:
    """Обученная модель: классификатор приборов и регрессор поправки.

    Списки колонок не хранятся отдельно — CatBoost сохраняет имена признаков
    внутри модели. Отдельный файл со списком мог бы разойтись с моделью,
    а `feature_names_` разойтись не может.
    """

    classifier: CatBoostClassifier
    regressor: CatBoostRegressor

    @property
    def classifier_columns(self) -> list[str]:
        return list(self.classifier.feature_names_)

    @property
    def regressor_columns(self) -> list[str]:
        return list(self.regressor.feature_names_)

    @property
    def polygons(self) -> list[str]:
        """Поля, на которых модель обучена.

        Восстанавливаются из колонок-доноров: у каждого поля обучающего
        набора своя колонка. Нужны, чтобы отличить знакомое поле от нового:
        для нового модель работает вне своей области определения.
        """
        prefix = "donor_"
        return sorted(
            column[len(prefix):]
            for column in self.regressor_columns
            if column.startswith(prefix)
        )

    @classmethod
    def load(cls, directory: Path) -> Artifacts:
        classifier = CatBoostClassifier()
        classifier.load_model(str(directory / CLASSIFIER_FILE))
        regressor = CatBoostRegressor()
        regressor.load_model(str(directory / REGRESSOR_FILE))
        return cls(classifier, regressor)

    @staticmethod
    def stored_in(directory: Path) -> bool:
        return all((directory / name).exists() for name in (CLASSIFIER_FILE, REGRESSOR_FILE))


def read_inputs(train_path: str | Path, test_path: str | Path) -> pd.DataFrame:
    """Прочитать опорный и целевой наборы из файлов в общий кадр.

    Строки с `is_synthetic_gap` маскируются целиком: скрыто не только
    `primary_ndvi`, но и индексы с погодой той же даты — это один снимок
    одного пролёта.
    """
    return v3.read_inputs(str(train_path), str(test_path))


def load_frame(source: str | Path | io.StringIO) -> pd.DataFrame:
    """Привести набор к виду, который ожидает модель.

    Год и день года из даты, сводные ряды EVI/NDWI, определение прибора
    по точному совпадению значения, приведение к шкале Landsat.
    """
    return v3.load(source)


def frame_from_rows(rows: list[dict]) -> pd.DataFrame:
    """Собрать кадр наблюдений из строк запроса.

    Строки проходят через тот же `load`, что и файл на диске: сериализация
    в буфер вместо повторения нормализации своими руками. Расхождение между
    веб-сценарием и batch-режимом означало бы, что модель на живых данных
    видит не то, на чём обучалась, — а такое расхождение не обнаруживается
    по результату, потому что числа остаются правдоподобными.
    """
    buffer = io.StringIO()
    pd.DataFrame(rows).to_csv(buffer, index=False)
    buffer.seek(0)
    return load_frame(buffer)


def combine(reference: pd.DataFrame, target: pd.DataFrame) -> pd.DataFrame:
    """Соединить опорный набор и целевые ряды в кадр для модели.

    Повторяет хвост `read_inputs` из V3 для кадров, уже находящихся в памяти:
    проверка ключей, разметка `split`, маскирование скрытых строк целиком
    и сквозная нумерация `row_id`.
    """
    if target.duplicated(v3.KEY).any():
        raise ValueError("целевой набор: неуникальный ключ поле + дата")

    target = target.copy()
    target["split"] = "test"
    if reference.empty:
        # Без опорного набора модель считает по одним лишь целевым рядам:
        # межполевые признаки окажутся пустыми. Предупреждение об этом
        # выдаёт вызывающая сторона, здесь просто нечего присоединять.
        combined = target
    else:
        if reference.duplicated(v3.KEY).any():
            raise ValueError("опорный набор: неуникальный ключ поле + дата")
        if len(reference[v3.KEY].merge(target[v3.KEY], on=v3.KEY)):
            raise ValueError("целевые ряды пересекаются с опорным набором по ключу поле + дата")
        reference = reference.copy()
        reference["split"] = "train"
        combined = pd.concat([reference, target], ignore_index=True)

    for column in SENSOR_COLUMNS:
        if column not in combined.columns:
            combined[column] = np.nan

    combined = v3.masked(combined, combined.index[combined.is_synthetic_gap.fillna(False)])
    combined["row_id"] = np.arange(len(combined))
    return combined


def predict(
    frame: pd.DataFrame, artifacts: Artifacts, target_ids: np.ndarray
) -> tuple[np.ndarray, pd.DataFrame]:
    """Предсказать NDVI для строк `target_ids`.

    `frame` — весь контекст целиком, а не только целевые строки: признаки
    считаются по соседним наблюдениям поля, по другим полям в ту же дату
    и по климатологии прошлых лет.

    Возвращает значения и кадр целевых строк с `polygon` и `date_str`,
    по которым предсказание сопоставляется с запросом. Порядок значений
    совпадает с порядком строк кадра.
    """
    target_rows = v3.samples(frame, target_ids)
    if target_rows.empty:
        return np.empty(0), target_rows

    logger.info("V6: признаки построены для %s целевых строк", len(target_rows))
    classifier_frame, tables = _tables(frame, target_rows)

    probabilities = artifacts.classifier.predict_proba(
        _aligned(classifier_frame, artifacts.classifier_columns, artifacts.classifier)
    )
    target = pd.concat(tables, ignore_index=True)
    residual = artifacts.regressor.predict(
        _aligned(target, artifacts.regressor_columns, artifacts.regressor)
    )
    values = np.clip(target[ANCHOR].to_numpy() + residual, *PREDICTION_RANGE)

    # Три блока предсказаний — по одному на прибор — сворачиваются
    # вероятностями того, каким прибором снята целевая дата.
    blended = (probabilities * np.stack(np.split(values, len(v3.SENSORS)), axis=1)).sum(1)
    return blended, target_rows


def _tables(visible: pd.DataFrame, base: pd.DataFrame) -> tuple[pd.DataFrame, list[pd.DataFrame]]:
    """Признаки классификатора приборов и по одной таблице на прибор.

    `scene_features` получает весь кадр как контекст: матрица ожидаемых
    значений по другим полям должна быть заполнена так же, как при обучении,
    когда в неё приходил кадр целиком. Признаки при этом считаются только
    для строк `base`.
    """
    classifier_frame, tables = v5.make_tables(v3, visible, base)
    extra = scene_features(v3, visible, base, context=_context(visible))
    return classifier_frame, [
        table.merge(addition, on="row_id", how="left", validate="one_to_one")
        for table, addition in zip(tables, extra, strict=True)
    ]


def _context(frame: pd.DataFrame) -> pd.DataFrame:
    """Перечень всех строк кадра в том виде, в каком его читает `scene_features`."""
    return pd.DataFrame(
        {
            "row_id": frame.row_id.to_numpy(),
            "polygon": frame.anon_polygon_id.to_numpy(),
            "date_str": frame.date.dt.strftime("%Y-%m-%d").to_numpy(),
            "year": frame.year.to_numpy(),
        }
    )


def _aligned(
    frame: pd.DataFrame, columns: list[str], model: CatBoostClassifier | CatBoostRegressor
) -> pd.DataFrame:
    """Привести кадр к колонкам, на которых обучена модель.

    Недостающие колонки добавляются пустыми: набор полей-доноров при
    предсказании может отличаться от обучающего, и отсутствие донора —
    это отсутствие значения, а не ошибка. Категориальные колонки CatBoost
    не принимает пустыми, поэтому пропуск в них заменяется строкой;
    незнакомое значение категории модель обрабатывает сама.
    """
    data = frame.reindex(columns=columns)
    for index in model.get_cat_feature_indices():
        name = columns[index]
        data[name] = data[name].astype(object).where(data[name].notna(), "").astype(str)
    return data
