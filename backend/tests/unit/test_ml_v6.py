"""Модель V6: обученные артефакты, предсказание и клиент.

Главная проверка — совпадение с эталонным submission. Она требует исходных
наборов задачи 1, которых в репозитории нет, и потому пропускается, если их
не положили рядом. Остальные проверки идут всегда.
"""

from __future__ import annotations

import inspect
from datetime import date, timedelta
from pathlib import Path

import pytest
from agropulse.ml.client import ImputeRequest, SeriesPoint
from agropulse.ml.v6 import pipeline
from agropulse.ml.v6_client import V6MLClient

ARTIFACTS = Path(__file__).resolve().parents[3] / "backend/agropulse/ml/v6/artifacts"

# Исходные наборы задачи 1 и эталон, собранный архивным кодом.
DATA = Path(__file__).resolve().parents[3] / "temp"
TRAIN = DATA / "train_dataset.csv"
TEST = DATA / "test_features.csv"
REFERENCE_SUBMISSION = DATA / "submissions/sub_14_v6_rerun.csv"

needs_datasets = pytest.mark.skipif(
    not (TRAIN.exists() and TEST.exists() and REFERENCE_SUBMISSION.exists()),
    reason="нет исходных наборов задачи 1",
)


# ----------------------------------------------------------------------
# Артефакты
# ----------------------------------------------------------------------


def test_trained_model_ships_with_the_code() -> None:
    """Модель обучена заранее и лежит в образе."""
    assert pipeline.Artifacts.stored_in(ARTIFACTS)

    artifacts = pipeline.Artifacts.load(ARTIFACTS)
    # Имена признаков хранит сам CatBoost, отдельного файла со списком нет.
    assert len(artifacts.regressor_columns) == 250
    assert len(artifacts.classifier_columns) == 131
    assert artifacts.polygons, "по колонкам-донорам восстанавливается состав полей"


def test_service_never_trains() -> None:
    """В сервисе выполняется только предсказание.

    Обучение занимает около пяти минут, и запуск его на запрос пользователя
    был бы не медленной работой, а другой архитектурой. Проверка сторожит
    именно это: `fit` в управляющем коде появиться не должен.
    """
    source = inspect.getsource(pipeline)
    assert ".fit(" not in source
    assert "Pool(" not in source


# ----------------------------------------------------------------------
# Предсказание
# ----------------------------------------------------------------------


@needs_datasets
def test_prediction_matches_reference_submission() -> None:
    """Предсказание по артефактам совпадает с эталоном архивного прогона.

    Архивный код обучал и предсказывал одним проходом; здесь обучение отделено
    и не выполняется вовсе. Совпадение доказывает, что разделение ничего
    не изменило — расхождение допускается лишь в пределах округления float.
    """
    import pandas as pd

    frame = pipeline.read_inputs(TRAIN, TEST)
    gaps = frame.loc[frame.is_synthetic_gap, "row_id"].to_numpy()
    values, rows = pipeline.predict(frame, pipeline.Artifacts.load(ARTIFACTS), gaps)

    got = (
        pd.DataFrame({"key": list(zip(rows.polygon, rows.date_str, strict=True)), "v": values})
        .set_index("key")
        .v.sort_index()
    )
    expected = pd.read_csv(REFERENCE_SUBMISSION)
    expected["date"] = pd.to_datetime(expected.date).dt.strftime("%Y-%m-%d")
    expected = (
        expected.assign(
            key=list(zip(expected.anon_polygon_id, expected.date, strict=True))
        )
        .set_index("key")
        .primary_ndvi_true.sort_index()
    )

    assert len(got) == len(expected) == 2323
    assert (got.index == expected.index).all()
    assert (got - expected).abs().max() < 1e-9


@needs_datasets
def test_scene_features_need_the_whole_frame_as_context() -> None:
    """Контекст `scene_features` — весь кадр, а не только целевые строки.

    Матрица ожидаемых значений заполняется только в ячейках переданных строк,
    а читаются из неё ожидания других полей той же съёмки. Если сузить её до
    целевых строк, признаки съёмки выродятся в пропуски, а предсказание
    останется правдоподобным по виду — поэтому проверка нужна отдельная.
    """
    from agropulse.ml.v6.scene_features import scene_features

    frame = pipeline.read_inputs(TRAIN, TEST)
    gaps = frame.loc[frame.is_synthetic_gap, "row_id"].to_numpy()[:200]
    target = pipeline.v3.samples(frame, gaps)

    narrow = scene_features(pipeline.v3, frame, target)[0]
    wide = scene_features(pipeline.v3, frame, target, context=pipeline._context(frame))[0]

    assert narrow.scene_global_count.max() == 0, "без контекста соседей не видно"
    assert wide.scene_global_count.max() > 0, "с контекстом соседи появляются"


# ----------------------------------------------------------------------
# Клиент
# ----------------------------------------------------------------------


def _series(days: int, start: date = date(2024, 5, 1)) -> list[SeriesPoint]:
    return [
        SeriesPoint(date=start + timedelta(days=offset * 5), primary_ndvi=0.3 + 0.01 * offset)
        for offset in range(days)
    ]


def _request(polygon: str, hidden: int = 5) -> ImputeRequest:
    observations = _series(12)
    target = observations[hidden].date
    return ImputeRequest(
        polygon_id=polygon,
        observations=[
            point if point.date != target else SeriesPoint(date=target, primary_ndvi=None)
            for point in observations
        ],
        targets=[target],
        crop_type="wheat",
    )


def test_client_reports_itself_unusable_without_reference_set() -> None:
    """Без опорного набора модель не притворяется работающей.

    Одно поле сравнивать не с чем, и межполевые признаки не просто пусты —
    расчёт обрывается. Поэтому клиент честно объявляет себя недоступным,
    а выбор реализации в `ml/resolve.py` сообщает причину в журнал.
    """
    client = V6MLClient(artifacts_dir=ARTIFACTS, reference_dataset=None)
    assert not client.is_available()

    missing = Path("/nonexistent/train_dataset.csv")
    assert not V6MLClient(artifacts_dir=ARTIFACTS, reference_dataset=missing).is_available()


@needs_datasets
def test_client_restores_a_web_field_against_the_reference_set() -> None:
    """Веб-сценарий: поле, которого не было в обучении, с опорным набором."""
    client = V6MLClient(artifacts_dir=ARTIFACTS, reference_dataset=TRAIN)
    assert client.is_available()

    request = _request("web-field-1")
    result = client.impute(request)

    assert result.source == "v6"
    assert result.model_version != "dev_stub"
    assert [item.date for item in result.predictions] == request.targets
    assert -0.1 <= result.predictions[0].value <= 1.0


@needs_datasets
def test_client_keeps_series_apart_in_one_batch() -> None:
    """Ряды считаются вместе, но результат раскладывается по своим полям."""
    client = V6MLClient(artifacts_dir=ARTIFACTS, reference_dataset=TRAIN)

    requests = [_request("web-field-1", hidden=5), _request("web-field-2", hidden=6)]
    results = client.impute_batch(requests)

    assert len(results) == 2
    for request, result in zip(requests, results, strict=True):
        assert [item.date for item in result.predictions] == request.targets


def test_client_forecast_is_not_attributed_to_v6() -> None:
    """V6 не прогнозирует, и выдавать климатический прогноз за неё нельзя."""
    from agropulse.ml.client import ForecastRequest

    client = V6MLClient(artifacts_dir=ARTIFACTS, reference_dataset=None)
    start = date(2024, 6, 1)
    result = client.forecast(
        ForecastRequest(
            polygon_id="field-1",
            observations=_series(8),
            horizon_days=7,
            climatology={
                start + timedelta(days=offset): (0.5, 0.05) for offset in range(60)
            },
        )
    )
    assert result.source == "climatology"
    assert result.source != V6MLClient.name
