"""Задачи пайплайна обработки поля."""

from __future__ import annotations

import logging
import uuid
from datetime import date

from sqlalchemy.dialects.postgresql import insert as pg_insert

from agropulse.db.models import Field, FieldStatus, Observation, ValueType
from agropulse.db.session import session_scope
from agropulse.geometry import to_geojson
from agropulse.providers.base import ProviderError, SatelliteObservation, SatelliteProvider
from agropulse.providers.satellite_gee import GEESatelliteProvider
from agropulse.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _satellite_providers() -> list[SatelliteProvider]:
    """Источники спутниковых данных в порядке предпочтения.

    На E2 сюда добавится STAC как резервный канал: если Earth Engine недоступен
    или исчерпал квоту, пайплайн должен продолжить работу, а не остановиться.
    """
    return [GEESatelliteProvider()]


def _store_observations(
    db, field_id: uuid.UUID, observations: list[SatelliteObservation]
) -> int:
    """Записать наблюдения через upsert.

    Именно upsert, а не insert: при `task_acks_late` задача может быть выполнена
    повторно после рестарта воркера, и уникальный ключ
    (field_id, date, value_type, source) обязан поглотить дубль.
    """
    if not observations:
        return 0

    rows = [
        {
            "field_id": field_id,
            "date": item.date,
            "value_type": ValueType.OBSERVED,
            "source": item.source,
            "ndvi_mean": item.ndvi_mean,
            "ndmi_mean": item.ndmi_mean,
            "evi_mean": item.evi_mean,
            "valid_fraction": item.valid_fraction,
            "cloud_fraction": item.cloud_fraction,
            "scene_id": item.scene_id,
            "missing_reason": item.missing_reason,
        }
        for item in observations
    ]

    statement = pg_insert(Observation).values(rows)
    statement = statement.on_conflict_do_update(
        constraint="uq_observation_identity",
        set_={
            column: statement.excluded[column]
            for column in (
                "ndvi_mean",
                "ndmi_mean",
                "evi_mean",
                "valid_fraction",
                "cloud_fraction",
                "scene_id",
                "missing_reason",
            )
        },
    )
    db.execute(statement)
    return len(rows)


def _collect_period(field: Field) -> tuple[date, date]:
    """Период сбора данных для поля."""
    project = field.project
    return project.period_from, project.period_to


@celery_app.task(name="agropulse.tasks.pipeline.collect_field_data", bind=True)
def collect_field_data(self, field_id: str) -> dict:
    """Собрать спутниковые наблюдения по одному полю.

    Очередь `collect`: задача упирается в сеть и длится минуты.
    Ошибка одного источника не роняет задачу — перебираются следующие,
    и лишь при отказе всех поле помечается как необеспеченное данными.
    """
    field_uuid = uuid.UUID(field_id)

    with session_scope() as db:
        field = db.get(Field, field_uuid)
        if field is None:
            logger.warning("Поле %s не найдено, задача пропущена", field_id)
            return {"field_id": field_id, "status": "not_found"}

        geometry = to_geojson(field.geom)
        date_from, date_to = _collect_period(field)

    observations: list[SatelliteObservation] = []
    errors: list[str] = []
    used_source: str | None = None

    for provider in _satellite_providers():
        if not provider.is_available():
            errors.append(f"{provider.name}: не сконфигурирован")
            continue
        try:
            observations = provider.fetch_series(geometry, date_from, date_to)
            used_source = provider.name
            break
        except ProviderError as exc:
            logger.warning("Источник %s не отработал: %s", provider.name, exc)
            errors.append(f"{provider.name}: {exc}")

    with session_scope() as db:
        field = db.get(Field, field_uuid)
        if field is None:
            return {"field_id": field_id, "status": "not_found"}

        stored = _store_observations(db, field_uuid, observations)
        usable = sum(1 for item in observations if item.ndvi_mean is not None)

        field.data_quality = {
            "source": used_source,
            "scenes_total": len(observations),
            "scenes_usable": usable,
            "period_from": date_from.isoformat(),
            "period_to": date_to.isoformat(),
            "provider_errors": errors or None,
        }

        if usable == 0:
            # Искусственный риск такому полю не выставляется: пользователь
            # должен видеть именно отсутствие данных, а не выдуманную оценку.
            field.status = FieldStatus.INSUFFICIENT_DATA

    logger.info(
        "Поле %s: сохранено %s дат, из них пригодных %s (источник %s)",
        field_id, stored, usable, used_source,
    )
    return {
        "field_id": field_id,
        "status": "ok" if usable else "insufficient_data",
        "stored": stored,
        "usable": usable,
        "source": used_source,
        "errors": errors or None,
    }


@celery_app.task(name="agropulse.tasks.pipeline.analyze_field", bind=True)
def analyze_field(self, field_id: str) -> dict:
    """Климатология, аномалии, составной риск и прогноз по одному полю.

    Очередь `analyze`. Содержательная часть появится на этапе E4.
    """
    logger.info("Анализ поля %s (заглушка, реализуется на E4)", field_id)
    return {"field_id": field_id, "status": "not_implemented"}
