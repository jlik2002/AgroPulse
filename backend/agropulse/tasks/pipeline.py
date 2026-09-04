"""Задачи пайплайна обработки поля.

Обработка разделена на две задачи по характеру нагрузки: `collect_field_data`
ходит во внешние источники и стоит в очереди `collect`, `analyze_field` считает
локально и стоит в очереди `analyze`. Поля обрабатываются независимо — отказ
на одном не останавливает остальные.

Обе задачи идемпотентны: при `task_acks_late` рестарт воркера возвращает задачу
в очередь, поэтому запись наблюдений идёт upsert'ом, а результаты анализа
полностью замещают предыдущие.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from agropulse.analytics import anomalies as anomalies_module
from agropulse.analytics import climatology as climatology_module
from agropulse.analytics import risk as risk_module
from agropulse.analytics.anomalies import SeriesSample
from agropulse.config import get_settings
from agropulse.db.models import (
    Anomaly,
    Field,
    FieldStatus,
    JobStatus,
    Observation,
    PipelineStage,
    ValueType,
)
from agropulse.db.session import session_scope
from agropulse.geometry import to_geojson
from agropulse.ml.baseline import BaselineMLClient
from agropulse.ml.client import ImputeRequest, SeriesPoint
from agropulse.providers import chain
from agropulse.tasks import progress
from agropulse.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

SOURCE_BASELINE = "baseline"


# ----------------------------------------------------------------------
# Сбор данных
# ----------------------------------------------------------------------


@celery_app.task(name="agropulse.tasks.pipeline.collect_field_data", bind=True)
def collect_field_data(self, field_id: str) -> dict:
    """Собрать спутниковые наблюдения и погоду по одному полю."""
    field_uuid = uuid.UUID(field_id)
    settings = get_settings()

    with session_scope() as db:
        field = db.get(Field, field_uuid)
        if field is None:
            logger.warning("Поле %s не найдено, задача пропущена", field_id)
            return {"field_id": field_id, "status": "not_found"}

        project_uuid = field.project_id
        geometry = to_geojson(field.geom)
        centroid = _centroid(geometry)
        period_from = field.project.period_from
        period_to = field.project.period_to

    # История за предыдущие сезоны нужна для климатической нормы. Пользователь
    # мог выбрать короткий период, но норму по нему не построить, поэтому
    # глубина запроса определяется настройкой, а не выбором в интерфейсе.
    history_from = date(period_from.year - settings.history_seasons, 1, 1)

    satellite = None
    weather = None
    errors: list[str] = []

    with progress.StageTracker(project_uuid, field_uuid, PipelineStage.SEARCH_SCENES) as stage:
        stage.message(f"период {history_from} — {period_to}")
        satellite = chain.fetch_satellite_series(geometry, history_from, period_to)
        errors += satellite.errors
        if not satellite.ok:
            raise RuntimeError("; ".join(satellite.errors) or "источники не вернули данных")
        stage.message(f"сцен получено: {len(satellite.items)}", 1.0)

    # Маскирование облаков и расчёт индексов выполняются внутри провайдера
    # одним серверным запросом, поэтому отдельными стадиями только отчитываемся.
    usable = sum(1 for item in satellite.items if item.ndvi_mean is not None)
    cloudy = len(satellite.items) - usable
    with progress.StageTracker(project_uuid, field_uuid, PipelineStage.CLOUD_MASKING) as stage:
        stage.message(f"непригодных по облачности: {cloudy}", 1.0)
    with progress.StageTracker(project_uuid, field_uuid, PipelineStage.INDICES) as stage:
        stage.message(f"индексы рассчитаны для {usable} дат", 1.0)

    with progress.StageTracker(project_uuid, field_uuid, PipelineStage.WEATHER) as stage:
        weather = chain.fetch_weather_history(
            centroid[0], centroid[1], history_from, period_to
        )
        errors += weather.errors
        # Погода — контекст, а не основа расчёта: её отсутствие ухудшает
        # объяснение аномалий, но не мешает их найти.
        stage.message(f"суток погоды: {len(weather.items)}", 1.0)

    with progress.StageTracker(project_uuid, field_uuid, PipelineStage.TIMESERIES):
        with session_scope() as db:
            stored = _store_observations(db, field_uuid, satellite.items, weather.items)
            field = db.get(Field, field_uuid)
            if field is not None:
                field.data_quality = {
                    "satellite_source": satellite.source,
                    "weather_source": weather.source,
                    "scenes_total": len(satellite.items),
                    "scenes_usable": usable,
                    "history_from": history_from.isoformat(),
                    "period_from": period_from.isoformat(),
                    "period_to": period_to.isoformat(),
                    "provider_errors": errors or None,
                }
                if usable == 0:
                    field.status = FieldStatus.INSUFFICIENT_DATA

    logger.info("Поле %s: сохранено %s дат, пригодных %s", field_id, stored, usable)
    return {
        "field_id": field_id,
        "status": "ok" if usable else "insufficient_data",
        "stored": stored,
        "usable": usable,
        "satellite_source": satellite.source,
        "weather_source": weather.source,
        "errors": errors or None,
    }


def _centroid(geometry: dict) -> tuple[float, float]:
    from shapely.geometry import shape

    point = shape(geometry).centroid
    return point.x, point.y


def _store_observations(db, field_id: uuid.UUID, satellite: list, weather: list) -> int:
    """Записать наблюдения, сшив спутниковые данные с погодой по дате."""
    if not satellite:
        return 0

    weather_by_date = {item.date: item for item in weather}

    rows = []
    for item in satellite:
        day_weather = weather_by_date.get(item.date)
        rows.append(
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
                "temperature": day_weather.temperature if day_weather else None,
                "precipitation": day_weather.precipitation if day_weather else None,
            }
        )

    statement = pg_insert(Observation).values(rows)
    statement = statement.on_conflict_do_update(
        constraint="uq_observation_identity",
        set_={
            column: statement.excluded[column]
            for column in (
                "ndvi_mean", "ndmi_mean", "evi_mean", "valid_fraction", "cloud_fraction",
                "scene_id", "missing_reason", "temperature", "precipitation",
            )
        },
    )
    db.execute(statement)
    return len(rows)


# ----------------------------------------------------------------------
# Анализ
# ----------------------------------------------------------------------


@celery_app.task(name="agropulse.tasks.pipeline.analyze_field", bind=True)
def analyze_field(self, field_id: str) -> dict:
    """Восстановить пропуски, найти аномалии, оценить риск."""
    field_uuid = uuid.UUID(field_id)

    with session_scope() as db:
        field = db.get(Field, field_uuid)
        if field is None:
            return {"field_id": field_id, "status": "not_found"}

        project_uuid = field.project_id
        sowing_date = field.sowing_date
        period_from = field.project.period_from
        period_to = field.project.period_to
        centroid = _centroid(to_geojson(field.geom))

        observations = db.scalars(
            select(Observation)
            .where(
                Observation.field_id == field_uuid,
                Observation.value_type == ValueType.OBSERVED,
            )
            .order_by(Observation.date)
        ).all()

        observed = [(o.date, o.ndvi_mean) for o in observations if o.ndvi_mean is not None]
        observed_dates = {day for day, _ in observed}
        weather_by_date = {o.date: (o.temperature, o.precipitation) for o in observations}
        ndmi_by_date = {o.date: o.ndmi_mean for o in observations if o.ndmi_mean is not None}
        valid_fractions = [
            o.valid_fraction for o in observations
            if o.ndvi_mean is not None and o.valid_fraction is not None
        ]

    # Погода нужна на каждый день сетки, а в наблюдениях она есть только на
    # датах сцен. Повторный запрос почти бесплатен: ответ лежит в кэше с
    # прошлой стадии сбора.
    daily_weather = chain.fetch_weather_history(centroid[0], centroid[1], period_from, period_to)
    for item in daily_weather.items:
        weather_by_date.setdefault(item.date, (item.temperature, item.precipitation))
        if weather_by_date[item.date] == (None, None):
            weather_by_date[item.date] = (item.temperature, item.precipitation)

    # Целевые даты восстановления — сплошная суточная сетка внутри периода
    # анализа. Дат, когда спутник не пролетал, в наблюдениях нет вовсе, поэтому
    # без такой сетки они бы остались дырой в графике: восстанавливать было бы
    # нечего. История прошлых сезонов остаётся на датах сцен — она нужна только
    # для климатической нормы, где окно и так ±15 дней.
    gap_dates = [
        period_from + timedelta(days=offset)
        for offset in range((period_to - period_from).days + 1)
        if (period_from + timedelta(days=offset)) not in observed_dates
    ]

    # --- восстановление пропусков ---
    restored: list = []
    with progress.StageTracker(project_uuid, field_uuid, PipelineStage.GAP_FILLING) as stage:
        # Пока задействован локальный baseline. Клиент внешнего сервиса моделей
        # подключается на E5 через тот же интерфейс MLClient.
        client = BaselineMLClient()
        result = client.impute(
            ImputeRequest(
                polygon_id=str(field_uuid),
                observations=[SeriesPoint(date=day, primary_ndvi=value) for day, value in observed],
                targets=gap_dates,
            )
        )
        restored = result.predictions
        stage.message(
            f"восстановлено {len(restored)} из {len(gap_dates)} дат суточной сетки", 1.0
        )

        with session_scope() as db:
            _store_restored(db, field_uuid, restored, weather_by_date)

    # --- климатология и аномалии ---
    with progress.StageTracker(project_uuid, field_uuid, PipelineStage.ANOMALIES) as stage:
        samples: list[SeriesSample] = [
            SeriesSample(
                date=day,
                ndvi=value,
                value_type=ValueType.OBSERVED,
                ndmi=ndmi_by_date.get(day),
                temperature=(weather_by_date.get(day) or (None, None))[0],
                precipitation=(weather_by_date.get(day) or (None, None))[1],
            )
            for day, value in observed
        ]
        samples += [
            SeriesSample(
                date=item.date,
                ndvi=item.value,
                value_type=ValueType.RESTORED,
                ndmi=ndmi_by_date.get(item.date),
                temperature=(weather_by_date.get(item.date) or (None, None))[0],
                precipitation=(weather_by_date.get(item.date) or (None, None))[1],
            )
            for item in restored
        ]

        # Норма строится по прошлым сезонам; текущий год исключается, иначе
        # аномалия вошла бы в собственную норму и замаскировала себя.
        in_period = [s for s in samples if period_from <= s.date <= period_to]
        climatology = climatology_module.build(
            history=[(s.date, s.ndvi) for s in samples],
            target_dates=[s.date for s in in_period],
            sowing_date=sowing_date,
            exclude_year=period_to.year,
        )
        periods, zscores = anomalies_module.detect(in_period, climatology, sowing_date)
        stage.message(
            f"аномальных периодов: {len(periods)}"
            if climatology.available
            else (climatology.reason or "норма не построена"),
            1.0,
        )

    # --- риск ---
    with progress.StageTracker(project_uuid, field_uuid, PipelineStage.RISK_FORECAST) as stage:
        # В оценку идут z-score, а не сырые значения: см. analytics/risk.py
        recent = [(day, z) for day, z in zscores.items()]
        restored_in_period = sum(1 for s in in_period if s.value_type == ValueType.RESTORED)
        assessment = risk_module.assess(
            anomalies=periods,
            recent_zscores=recent,
            observed_count=sum(1 for s in in_period if s.value_type == ValueType.OBSERVED),
            mean_valid_fraction=(
                sum(valid_fractions) / len(valid_fractions) if valid_fractions else None
            ),
            restored_fraction=(restored_in_period / len(in_period)) if in_period else 0.0,
            climatology_available=climatology.available,
        )
        stage.message(
            f"риск {assessment.score}" if assessment.score is not None
            else (assessment.insufficient_reason or "риск не рассчитан"),
            1.0,
        )

    with session_scope() as db:
        _store_analysis(db, field_uuid, periods, zscores, assessment, climatology)

    # Стадия визуализации на текущем этапе ничего не готовит: слои снимков
    # добавляются позже. Отмечаем её, чтобы список стадий был полным.
    with progress.StageTracker(project_uuid, field_uuid, PipelineStage.VISUALIZATION) as stage:
        stage.message("данные готовы к отображению", 1.0)

    summary = {
        "status": assessment.status.value,
        "risk_score": assessment.score,
        "anomalies": len(periods),
        "restored": len(restored),
    }
    progress.field_finished(project_uuid, field_uuid, assessment.status.value, summary)

    logger.info("Поле %s: %s", field_id, summary)
    return {"field_id": field_id, **summary}


def _store_restored(db, field_id: uuid.UUID, predictions: list, weather_by_date: dict) -> None:
    """Заместить восстановленные значения.

    Сначала удаляем прежние: изменившийся набор наблюдений мог сделать часть
    старых восстановлений неверными, а upsert оставил бы их в ряду.
    """
    db.execute(
        delete(Observation).where(
            Observation.field_id == field_id,
            Observation.value_type == ValueType.RESTORED,
        )
    )
    if not predictions:
        return

    rows = []
    for item in predictions:
        temperature, precipitation = weather_by_date.get(item.date) or (None, None)
        rows.append(
            {
                "field_id": field_id,
                "date": item.date,
                "value_type": ValueType.RESTORED,
                "source": SOURCE_BASELINE,
                "ndvi_mean": item.value,
                "confidence": item.confidence,
                "temperature": temperature,
                "precipitation": precipitation,
            }
        )
    db.execute(pg_insert(Observation).values(rows))


def _store_analysis(
    db, field_id: uuid.UUID, periods: list, zscores: dict, assessment, climatology
) -> None:
    """Записать аномалии, z-score и оценку риска."""
    db.execute(delete(Anomaly).where(Anomaly.field_id == field_id))
    for period in periods:
        db.add(
            Anomaly(
                field_id=field_id,
                start_date=period.start_date,
                end_date=period.end_date,
                duration_days=period.duration_days,
                severity=period.severity,
                max_zscore=period.max_zscore,
                mean_zscore=period.mean_zscore,
                restored_fraction=period.restored_fraction,
                confidence=period.confidence,
                factors=period.factors,
            )
        )

    for observation in db.scalars(
        select(Observation).where(Observation.field_id == field_id)
    ).all():
        observation.ndvi_zscore = zscores.get(observation.date)

    field = db.get(Field, field_id)
    if field is None:
        return

    field.status = assessment.status
    field.risk_score = assessment.score
    field.risk_breakdown = {
        "score": assessment.score,
        "weights": assessment.breakdown,
        "explanation": assessment.explanation,
        "confidence": assessment.confidence,
        "insufficient_reason": assessment.insufficient_reason,
        "climatology": {
            "available": climatology.available,
            "phase_kind": climatology.phase_kind,
            "sowing_known": climatology.sowing_known,
            "seasons_used": climatology.seasons_used,
            "samples": climatology.samples_total,
            "reason": climatology.reason,
        },
    }


@celery_app.task(name="agropulse.tasks.pipeline.process_field", bind=True)
def process_field(self, field_id: str) -> dict:
    """Полный цикл по полю: сбор и следом анализ.

    Отдельная задача-обёртка нужна, чтобы интерфейс запускал обработку одним
    вызовом, а не выстраивал цепочку сам.
    """
    collected = collect_field_data.run(field_id)
    if collected.get("status") == "not_found":
        return collected
    analyzed = analyze_field.run(field_id)
    return {**collected, **analyzed}
