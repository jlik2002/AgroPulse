"""Пайплайн обработки поля.

Проверяется то, ради чего пайплайн переписывался: идемпотентность повтора,
конечный статус при неудаче и разделение временных ошибок от окончательных.
Внешние источники и сервис моделей подменяются — тест не должен зависеть
от доступности Earth Engine.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.usefixtures("database")


class StubMLClient:
    """Клиент моделей, возвращающий предсказуемый результат."""

    name = "stub"

    def is_available(self) -> bool:
        return True

    def impute(self, request):
        from agropulse.ml.client import ImputeResult, Prediction

        return ImputeResult(
            predictions=[
                Prediction(date=day, value=0.5, confidence=0.9) for day in request.targets[:3]
            ],
            model_version="stub",
            source=self.name,
        )

    def forecast(self, request):
        from agropulse.ml.client import ForecastPoint, ForecastResult

        start = max(point.date for point in request.observations)
        return ForecastResult(
            points=[
                ForecastPoint(date=start + timedelta(days=offset), value=0.4, low=0.3, high=0.5)
                for offset in range(1, 4)
            ],
            model_version="stub",
            source=self.name,
            direction="declining",
            risk_level="moderate",
            confidence=0.7,
        )


@pytest.fixture
def satellite_series(monkeypatch):
    """Ряд наблюдений вместо обращения к Earth Engine."""
    from agropulse.providers import chain
    from agropulse.providers.base import SatelliteObservation, WeatherObservation

    def _fetch_satellite(geometry, date_from, date_to):
        result = chain.SourceResult()
        day = date(2024, 5, 1)
        result.items = [
            SatelliteObservation(
                date=day + timedelta(days=offset * 5),
                source="s2_gee",
                ndvi_mean=0.6 - offset * 0.02,
                ndmi_mean=0.3,
                valid_fraction=0.9,
                cloud_fraction=0.05,
                scene_id=f"scene-{offset}",
            )
            for offset in range(8)
        ]
        result.source = "s2_gee"
        return result

    def _fetch_weather(lon, lat, date_from, date_to):
        result = chain.SourceResult()
        result.items = [
            WeatherObservation(date=date_from + timedelta(days=offset), temperature=20.0,
                               precipitation=1.0)
            for offset in range((date_to - date_from).days + 1)
        ]
        result.source = "open_meteo"
        return result

    def _fetch_forecast(lon, lat, days):
        result = chain.SourceResult()
        result.source = "open_meteo"
        return result

    monkeypatch.setattr(chain, "fetch_satellite_series", _fetch_satellite)
    monkeypatch.setattr(chain, "fetch_weather_history", _fetch_weather)
    monkeypatch.setattr(chain, "fetch_weather_forecast", _fetch_forecast)


@pytest.fixture
def pipeline():
    from agropulse.config import get_settings
    from agropulse.services.pipeline import FieldPipeline

    return FieldPipeline(get_settings(), ml_client=StubMLClient(), task_id="test-task")


def _field_id(created_field: dict) -> uuid.UUID:
    return uuid.UUID(created_field["id"])


# ----------------------------------------------------------------------


def test_collect_stores_observations_and_data_quality(
    pipeline, satellite_series, created_field, db_session
) -> None:
    from agropulse.db.models import Field, Observation, ValueType

    field_id = _field_id(created_field)

    result = pipeline.collect(field_id)

    assert result["status"] == "ok"
    assert result["stored"] == 8
    assert result["satellite_source"] == "s2_gee"

    stored = (
        db_session.query(Observation)
        .filter_by(field_id=field_id, value_type=ValueType.OBSERVED)
        .count()
    )
    assert stored == 8

    field = db_session.get(Field, field_id)
    db_session.refresh(field)
    assert field.data_quality["scenes_usable"] == 8


def test_collect_is_idempotent(
    pipeline, satellite_series, created_field, db_session
) -> None:
    """Повторный прогон обновляет строки, а не удваивает ряд.

    Это не теоретическая осторожность: при `task_acks_late` рестарт воркера
    возвращает задачу в очередь, и повтор гарантированно случится.
    """
    from agropulse.db.models import Observation

    field_id = _field_id(created_field)

    pipeline.collect(field_id)
    pipeline.collect(field_id)

    assert db_session.query(Observation).filter_by(field_id=field_id).count() == 8


def test_analyze_writes_results_and_marks_status(
    pipeline, satellite_series, created_field, db_session
) -> None:
    from agropulse.db.models import Field, ForecastRun, Observation, ValueType

    field_id = _field_id(created_field)
    pipeline.collect(field_id)

    result = pipeline.analyze(field_id)

    assert result["field_id"] == str(field_id)
    assert result["restored"] == 3
    assert result["forecast_days"] == 3

    restored = (
        db_session.query(Observation)
        .filter_by(field_id=field_id, value_type=ValueType.RESTORED)
        .count()
    )
    assert restored == 3
    assert db_session.query(ForecastRun).filter_by(field_id=field_id).count() == 1

    field = db_session.get(Field, field_id)
    db_session.refresh(field)
    assert field.status.value != "pending"


def test_analyze_is_idempotent(
    pipeline, satellite_series, created_field, db_session
) -> None:
    """Результаты анализа замещаются, а не накапливаются."""
    from agropulse.db.models import Anomaly, ForecastRun, Observation, ValueType

    field_id = _field_id(created_field)
    pipeline.collect(field_id)

    pipeline.analyze(field_id)
    first_anomalies = db_session.query(Anomaly).filter_by(field_id=field_id).count()
    pipeline.analyze(field_id)

    assert db_session.query(Anomaly).filter_by(field_id=field_id).count() == first_anomalies
    assert db_session.query(ForecastRun).filter_by(field_id=field_id).count() == 1
    assert (
        db_session.query(Observation)
        .filter_by(field_id=field_id, value_type=ValueType.RESTORED)
        .count()
        == 3
    )


def test_missing_field_is_not_an_error(pipeline) -> None:
    """Поле могли удалить, пока задача стояла в очереди."""
    from agropulse.services.pipeline import FieldMissing

    with pytest.raises(FieldMissing):
        pipeline.collect(uuid.uuid4())


def test_provider_failure_is_retryable(
    pipeline, monkeypatch, created_field
) -> None:
    """Отказ источника — временная ошибка: повтор имеет смысл."""
    from agropulse.errors import TransientPipelineError
    from agropulse.providers import chain

    def _failing(geometry, date_from, date_to):
        result = chain.SourceResult()
        result.failures.append("s2_gee: сеть недоступна")
        return result

    monkeypatch.setattr(chain, "fetch_satellite_series", _failing)

    with pytest.raises(TransientPipelineError):
        pipeline.collect(_field_id(created_field))


def test_empty_period_is_permanent_failure(
    pipeline, monkeypatch, created_field
) -> None:
    """За прошедший период снимки не появятся — повторять бессмысленно."""
    from agropulse.errors import InsufficientDataError
    from agropulse.providers import chain

    def _empty(geometry, date_from, date_to):
        result = chain.SourceResult()
        result.empty_sources.append("s2_gee")
        return result

    monkeypatch.setattr(chain, "fetch_satellite_series", _empty)

    with pytest.raises(InsufficientDataError):
        pipeline.collect(_field_id(created_field))


def test_mark_failed_gives_field_a_final_status(pipeline, created_field, db_session) -> None:
    """Поле не должно навсегда остаться в ожидании обработки."""
    from agropulse.db.models import Field, FieldStatus

    field_id = _field_id(created_field)

    pipeline.mark_failed(field_id, "collect_failed")

    field = db_session.get(Field, field_id)
    db_session.refresh(field)
    assert field.status == FieldStatus.FAILED
    # Наружу уходит код, а не текст исключения.
    assert field.data_quality["last_error"] == "collect_failed"


def test_mark_failed_on_deleted_field_is_silent(pipeline) -> None:
    pipeline.mark_failed(uuid.uuid4(), "collect_failed")


def test_progress_stages_are_recorded(
    pipeline, satellite_series, created_field, db_session
) -> None:
    """Пользователь должен видеть продвижение по стадиям."""
    from agropulse.db.models import Job, JobStatus

    field_id = _field_id(created_field)

    pipeline.collect(field_id)

    jobs = db_session.query(Job).filter_by(field_id=field_id).all()
    stages = {job.stage.value for job in jobs}
    assert stages == {
        "search_scenes",
        "cloud_masking",
        "indices",
        "weather",
        "timeseries",
    }
    assert all(job.status == JobStatus.DONE for job in jobs)


def test_failed_stage_is_visible_to_the_user(
    pipeline, monkeypatch, created_field, db_session
) -> None:
    """Упавшая стадия обязана быть видна, а не молча оборвать поток событий."""
    from agropulse.db.models import Job, JobStatus, PipelineStage
    from agropulse.errors import TransientPipelineError
    from agropulse.providers import chain

    def _failing(geometry, date_from, date_to):
        result = chain.SourceResult()
        result.failures.append("s2_gee: сеть недоступна")
        return result

    monkeypatch.setattr(chain, "fetch_satellite_series", _failing)

    field_id = _field_id(created_field)
    with pytest.raises(TransientPipelineError):
        pipeline.collect(field_id)

    job = (
        db_session.query(Job)
        .filter_by(field_id=field_id, stage=PipelineStage.SEARCH_SCENES)
        .one()
    )
    assert job.status == JobStatus.FAILED
    assert job.error
