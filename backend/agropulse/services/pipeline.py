"""Обработка поля: сбор данных и анализ.

Здесь лежит вся логика пайплайна. Celery-задачи в `tasks/pipeline.py` —
тонкие адаптеры: они разбирают аргументы, задают политику повторов и вызывают
эти методы. Благодаря этому обработку поля можно выполнить и проверить без
брокера, а сама логика не зависит от способа запуска.

Обработка разделена на две операции по характеру нагрузки: `collect` ходит
во внешние источники, `analyze` считает локально. Поля обрабатываются
независимо — отказ на одном не останавливает остальные.

Обе операции идемпотентны: при `task_acks_late` рестарт воркера возвращает
задачу в очередь, поэтому наблюдения пишутся upsert'ом, а результаты анализа
полностью замещают предыдущие.

Ошибки разделены на временные и окончательные. Временная (`TransientPipelineError`)
означает, что повтор имеет смысл: сеть, внешний источник, недоступный сервис
моделей. Всё остальное повторять бессмысленно, и поле сразу получает конечный
статус `failed` с причиной — запись не должна навсегда остаться в `pending`.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date, timedelta

from agropulse.analytics import anomalies as anomalies_module
from agropulse.analytics import climatology as climatology_module
from agropulse.analytics import radar as radar_module
from agropulse.analytics import risk as risk_module
from agropulse.analytics.anomalies import AnomalyPeriod, SeriesSample
from agropulse.analytics.climatology import Climatology, phase_of
from agropulse.analytics.radar import RadarSample
from agropulse.analytics.risk import RiskAssessment
from agropulse.config import Settings
from agropulse.db.models import (
    Anomaly,
    Field,
    FieldStatus,
    ForecastRun,
    PipelineStage,
    ValueType,
)
from agropulse.db.uow import UnitOfWork, unit_of_work
from agropulse.errors import InsufficientDataError, TransientPipelineError, UpstreamError
from agropulse.geometry import centroid as geometry_centroid
from agropulse.geometry import to_geojson
from agropulse.ml.client import (
    ForecastRequest,
    ForecastResult,
    ImputeRequest,
    MLClient,
    Prediction,
    SeriesPoint,
    WeatherPoint,
)
from agropulse.ml.resolve import get_client
from agropulse.providers import chain
from agropulse.services import progress

logger = logging.getLogger(__name__)

# Погода привязана к дате; отсутствие значений на дату — норма, а не ошибка.
_NO_WEATHER: tuple[float | None, float | None] = (None, None)


class FieldMissing(Exception):
    """Поле удалили, пока задача стояла в очереди.

    Не ошибка: пользователь имел право удалить поле. Задача завершается
    штатно и ничего не делает.
    """


@dataclass(slots=True)
class CollectContext:
    """Всё, что нужно для сбора, прочитанное одной транзакцией."""

    field_id: uuid.UUID
    project_id: uuid.UUID
    geometry: dict
    centroid: tuple[float, float]
    period_from: date
    period_to: date
    history_from: date


@dataclass(slots=True)
class AnalysisContext:
    """Состояние ряда поля на момент анализа."""

    field_id: uuid.UUID
    project_id: uuid.UUID
    sowing_date: date | None
    period_from: date
    period_to: date
    centroid: tuple[float, float]
    observed: list[tuple[date, float]]
    ndmi_by_date: dict[date, float]
    weather_by_date: dict[date, tuple[float | None, float | None]]
    valid_fractions: list[float]
    cloud_by_date: dict[date, float] = dataclass_field(default_factory=dict)
    radar: list[RadarSample] = dataclass_field(default_factory=list)

    @property
    def observed_dates(self) -> set[date]:
        return {day for day, _ in self.observed}


@dataclass(slots=True)
class AnalysisOutcome:
    """Результаты расчёта до записи в базу."""

    samples: list[SeriesSample]
    restored: list[Prediction]
    restored_source: str
    climatology: Climatology
    periods: list[AnomalyPeriod]
    zscores: dict[date, float]
    forecast: ForecastResult
    assessment: RiskAssessment
    # Производные величины радарного ряда по датам и найденные в нём события.
    radar_derived: dict[date, dict] = dataclass_field(default_factory=dict)
    radar_events: list[radar_module.RadarEvent] = dataclass_field(default_factory=list)
    in_period: list[SeriesSample] = dataclass_field(default_factory=list)
    # Коридор нормы по датам периода: (нижняя граница, верхняя). Из него
    # интерфейс строит «ожидаемую динамику» — середину коридора.
    norm_bands: dict[date, tuple[float, float]] = dataclass_field(default_factory=dict)


class FieldPipeline:
    """Обработка одного поля.

    Внешние зависимости передаются в конструктор, а не берутся из глобалей:
    так сценарий можно прогнать с подменённым клиентом моделей и без сети.
    """

    def __init__(
        self,
        settings: Settings,
        ml_client: MLClient | None = None,
        task_id: str | None = None,
    ) -> None:
        self._settings = settings
        self._ml_client = ml_client
        self._task_id = task_id

    # ------------------------------------------------------------------
    # Сбор данных
    # ------------------------------------------------------------------

    def collect(self, field_id: uuid.UUID) -> dict:
        """Собрать спутниковые наблюдения и погоду по одному полю."""
        context = self._load_collect_context(field_id)

        satellite = self._search_scenes(context)
        usable = sum(1 for item in satellite.items if item.ndvi_mean is not None)
        self._report_masking_stages(context, satellite, usable)
        radar = self._fetch_radar(context)
        weather = self._fetch_weather(context)

        errors = satellite.errors + radar.errors + weather.errors
        stored = self._store_timeseries(context, satellite, weather, usable, errors)
        radar_stored = self._store_radar(context, radar)

        logger.info(
            "field_collected",
            extra={
                "field_id": str(field_id),
                "stored": stored,
                "usable": usable,
                "radar_stored": radar_stored,
                "satellite_source": satellite.source,
            },
        )
        return {
            "field_id": str(field_id),
            "status": "ok" if usable else "insufficient_data",
            "stored": stored,
            "usable": usable,
            "radar_stored": radar_stored,
            "satellite_source": satellite.source,
            "radar_source": radar.source,
            "weather_source": weather.source,
            "errors": errors or None,
        }

    def _load_collect_context(self, field_id: uuid.UUID) -> CollectContext:
        with unit_of_work() as uow:
            field = self._require_field(uow, field_id)
            geometry = to_geojson(field.geom)
            period_from = field.project.period_from
            period_to = field.project.period_to

            return CollectContext(
                field_id=field_id,
                project_id=field.project_id,
                geometry=geometry,
                centroid=geometry_centroid(geometry),
                period_from=period_from,
                period_to=period_to,
                # История за предыдущие сезоны нужна для климатической нормы.
                # Пользователь мог выбрать короткий период, но норму по нему
                # не построить, поэтому глубина запроса определяется настройкой,
                # а не выбором в интерфейсе.
                history_from=date(period_from.year - self._settings.history_seasons, 1, 1),
            )

    def _search_scenes(self, context: CollectContext):
        with self._stage(
            context.project_id, context.field_id, PipelineStage.SEARCH_SCENES
        ) as stage:
            stage.message(f"период {context.history_from} — {context.period_to}")
            satellite = chain.fetch_satellite_series(
                context.geometry, context.history_from, context.period_to
            )
            if not satellite.ok:
                raise _no_data_error(satellite, "спутниковые источники не вернули данных")
            stage.message(f"сцен получено: {len(satellite.items)}", 1.0)
        return satellite

    def _report_masking_stages(self, context: CollectContext, satellite, usable: int) -> None:
        """Отчитаться о стадиях, выполненных на стороне провайдера.

        Маскирование облаков и расчёт индексов делаются внутри провайдера одним
        серверным запросом. Отдельными стадиями они существуют только в
        интерфейсе: пользователь должен видеть, что и это было сделано.
        """
        cloudy = len(satellite.items) - usable
        with self._stage(
            context.project_id, context.field_id, PipelineStage.CLOUD_MASKING
        ) as stage:
            stage.message(f"непригодных по облачности: {cloudy}", 1.0)
        with self._stage(context.project_id, context.field_id, PipelineStage.INDICES) as stage:
            stage.message(f"индексы рассчитаны для {usable} дат", 1.0)

    def _fetch_radar(self, context: CollectContext):
        """Собрать радарный ряд Sentinel-1.

        Радар — дополнение, а не основа: его отказ снижает подтверждённость
        выводов, но не мешает посчитать поле. Поэтому стадия завершается
        штатно даже при пустом ответе, а причина уходит в качество данных.
        """
        with self._stage(context.project_id, context.field_id, PipelineStage.RADAR) as stage:
            radar = chain.fetch_radar_series(
                context.geometry, context.history_from, context.period_to
            )
            usable = sum(1 for item in radar.items if item.vh_median_db is not None)
            stage.message(f"радарных съёмок пригодных: {usable}", 1.0)
        return radar

    def _store_radar(self, context: CollectContext, radar) -> int:
        if not radar.items:
            return 0
        with unit_of_work() as uow:
            return uow.radar.upsert(_radar_rows(context.field_id, radar.items))

    def _fetch_weather(self, context: CollectContext):
        with self._stage(context.project_id, context.field_id, PipelineStage.WEATHER) as stage:
            weather = chain.fetch_weather_history(
                context.centroid[0], context.centroid[1],
                context.history_from, context.period_to,
            )
            # Погода — контекст, а не основа расчёта: её отсутствие ухудшает
            # объяснение аномалий, но не мешает их найти.
            stage.message(f"суток погоды: {len(weather.items)}", 1.0)
        return weather

    def _store_timeseries(
        self, context: CollectContext, satellite, weather, usable: int, errors: list[str]
    ) -> int:
        with self._stage(context.project_id, context.field_id, PipelineStage.TIMESERIES):
            with unit_of_work() as uow:
                stored = uow.observations.upsert_observed(
                    _observation_rows(context.field_id, satellite.items, weather.items)
                )
                field = uow.fields.get(context.field_id)
                if field is not None:
                    field.data_quality = {
                        "satellite_source": satellite.source,
                        "weather_source": weather.source,
                        "scenes_total": len(satellite.items),
                        "scenes_usable": usable,
                        "history_from": context.history_from.isoformat(),
                        "period_from": context.period_from.isoformat(),
                        "period_to": context.period_to.isoformat(),
                        "provider_errors": errors or None,
                    }
                    if usable == 0:
                        field.status = FieldStatus.INSUFFICIENT_DATA
        return stored

    # ------------------------------------------------------------------
    # Анализ
    # ------------------------------------------------------------------

    def analyze(self, field_id: uuid.UUID) -> dict:
        """Восстановить пропуски, найти аномалии, оценить риск и прогноз."""
        context = self._load_analysis_context(field_id)
        client = self._resolve_ml_client()

        outcome = self._compute(context, client)
        self._store_analysis(context, outcome)
        self._report_visualization(context)

        summary = {
            "status": outcome.assessment.status.value,
            "risk_score": outcome.assessment.score,
            "anomalies": len(outcome.periods),
            "restored": len(outcome.restored),
            "forecast_days": len(outcome.forecast.points),
            "forecast_direction": outcome.forecast.direction,
        }
        progress.field_finished(
            context.project_id, field_id, outcome.assessment.status.value, summary
        )
        logger.info("field_analyzed", extra={"field_id": str(field_id), **summary})
        return {"field_id": str(field_id), **summary}

    def _load_analysis_context(self, field_id: uuid.UUID) -> AnalysisContext:
        with unit_of_work() as uow:
            field = self._require_field(uow, field_id)
            observations = uow.observations.list_for_field(field_id, (ValueType.OBSERVED,))
            radar_rows = uow.radar.list_for_field(field_id)

            context = AnalysisContext(
                field_id=field_id,
                project_id=field.project_id,
                sowing_date=field.sowing_date,
                period_from=field.project.period_from,
                period_to=field.project.period_to,
                centroid=geometry_centroid(to_geojson(field.geom)),
                observed=[
                    (o.date, o.ndvi_mean) for o in observations if o.ndvi_mean is not None
                ],
                ndmi_by_date={
                    o.date: o.ndmi_mean for o in observations if o.ndmi_mean is not None
                },
                weather_by_date={
                    o.date: (o.temperature, o.precipitation) for o in observations
                },
                valid_fractions=[
                    o.valid_fraction
                    for o in observations
                    if o.ndvi_mean is not None and o.valid_fraction is not None
                ],
                cloud_by_date={
                    o.date: o.cloud_fraction
                    for o in observations
                    if o.cloud_fraction is not None
                },
                radar=[_to_radar_sample(row) for row in radar_rows],
            )

        self._fill_daily_weather(context)
        return context

    def _fill_daily_weather(self, context: AnalysisContext) -> None:
        """Дополнить погоду до суточной сетки.

        В наблюдениях погода есть только на датах сцен, а анализу она нужна
        на каждый день периода. Повторный запрос почти бесплатен: ответ лежит
        в кэше с прошлой стадии сбора.
        """
        daily = chain.fetch_weather_history(
            context.centroid[0], context.centroid[1], context.period_from, context.period_to
        )
        for item in daily.items:
            known = context.weather_by_date.get(item.date)
            if known is None or known == _NO_WEATHER:
                context.weather_by_date[item.date] = (item.temperature, item.precipitation)

    def _compute(self, context: AnalysisContext, client: MLClient) -> AnalysisOutcome:
        restored, restored_source = self._restore_gaps(context, client)
        samples = _build_samples(context, restored)
        in_period = [
            sample
            for sample in samples
            if context.period_from <= sample.date <= context.period_to
        ]

        climatology, periods, zscores = self._detect_anomalies(context, samples, in_period)

        # Радар не участвует в поиске аномалий и не меняет их границы: событие
        # находится по оптике, а радар отвечает на отдельный вопрос — сошлись
        # ли на нём независимые способы измерения.
        radar_derived, radar_events = self._analyze_radar(context, periods, in_period)

        # Прогноз и риск считаются в одной стадии: пользователю они
        # показываются вместе и по отдельности смысла не имеют.
        with self._stage(
            context.project_id, context.field_id, PipelineStage.RISK_FORECAST
        ) as stage:
            forecast = self._build_forecast(context, client, samples, climatology)
            stage.message(
                f"прогноз на {len(forecast.points)} суток, динамика {forecast.direction}"
                if forecast.points
                else f"прогноз не построен: {forecast.insufficient_reason}",
                0.5,
            )
            assessment = self._assess_risk(context, periods, zscores, in_period, climatology)
            stage.message(
                f"риск {assessment.score}"
                if assessment.score is not None
                else (assessment.insufficient_reason or "риск не рассчитан"),
                1.0,
            )

        return AnalysisOutcome(
            samples=samples,
            restored=restored,
            restored_source=restored_source,
            climatology=climatology,
            periods=periods,
            zscores=zscores,
            forecast=forecast,
            assessment=assessment,
            radar_derived=radar_derived,
            radar_events=radar_events,
            in_period=in_period,
            norm_bands=_norm_bands(climatology, in_period),
        )

    def _analyze_radar(
        self,
        context: AnalysisContext,
        periods: list[AnomalyPeriod],
        in_period: list[SeriesSample],
    ) -> tuple[dict[date, dict], list[radar_module.RadarEvent]]:
        """Посчитать производные радарного ряда и подтвердить ими аномалии.

        Отсутствие радара — штатная ситуация: поле могло быть собрано до
        появления этого источника, а Earth Engine мог быть недоступен. Тогда
        подтверждённость считается по одной оптике и погоде, и это честно
        отражается в её составе.
        """
        if not context.radar:
            for period in periods:
                _apply_corroboration(period, context, in_period, samples=[], events=[])
            return {}, []

        derived = radar_module.derive(context.radar)
        events = radar_module.detect_events(context.radar, derived)
        for period in periods:
            _apply_corroboration(
                period, context, in_period, samples=context.radar, events=events
            )
        return derived, events

    def _restore_gaps(
        self, context: AnalysisContext, client: MLClient
    ) -> tuple[list[Prediction], str]:
        """Восстановить пропуски на суточной сетке периода анализа.

        Целевые даты — сплошная суточная сетка внутри периода. Дат, когда
        спутник не пролетал, в наблюдениях нет вовсе, поэтому без такой сетки
        они остались бы дырой в графике: восстанавливать было бы нечего.
        История прошлых сезонов остаётся на датах сцен — она нужна только для
        климатической нормы, где окно и так ±15 дней.
        """
        observed_dates = context.observed_dates
        gap_dates = [
            day
            for day in _days_between(context.period_from, context.period_to)
            if day not in observed_dates
        ]

        with self._stage(
            context.project_id, context.field_id, PipelineStage.GAP_FILLING
        ) as stage:
            result = _call_model(
                lambda: client.impute(
                    ImputeRequest(
                        polygon_id=str(context.field_id),
                        observations=[
                            SeriesPoint(date=day, primary_ndvi=value)
                            for day, value in context.observed
                        ],
                        targets=gap_dates,
                    )
                )
            )
            stage.message(
                f"восстановлено {len(result.predictions)} из {len(gap_dates)} "
                "дат суточной сетки",
                1.0,
            )
        return result.predictions, result.source

    def _detect_anomalies(
        self,
        context: AnalysisContext,
        samples: list[SeriesSample],
        in_period: list[SeriesSample],
    ) -> tuple[Climatology, list[AnomalyPeriod], dict[date, float]]:
        with self._stage(context.project_id, context.field_id, PipelineStage.ANOMALIES) as stage:
            # Целевые фазы включают горизонт прогноза: без этого норма
            # не покроет будущие даты и прогноз строить будет не от чего.
            last_observed = max((sample.date for sample in samples), default=context.period_to)
            forecast_dates = _days_after(last_observed, self._settings.forecast_horizon_days)

            # Норма строится по прошлым сезонам; текущий год исключается,
            # иначе аномалия вошла бы в собственную норму и замаскировала себя.
            climatology = climatology_module.build(
                history=[(sample.date, sample.ndvi) for sample in samples],
                target_dates=[sample.date for sample in in_period] + forecast_dates,
                sowing_date=context.sowing_date,
                exclude_year=context.period_to.year,
            )
            periods, zscores = anomalies_module.detect(
                in_period, climatology, context.sowing_date
            )
            stage.message(
                f"аномальных периодов: {len(periods)}"
                if climatology.available
                else (climatology.reason or "норма не построена"),
                1.0,
            )
        return climatology, periods, zscores

    def _build_forecast(
        self,
        context: AnalysisContext,
        client: MLClient,
        samples: list[SeriesSample],
        climatology: Climatology,
    ) -> ForecastResult:
        """Построить прогноз NDVI на горизонт вперёд.

        Норма нужна на будущие даты, а `Climatology` рассчитана по фазам,
        встреченным в прошлом. Поэтому оценки для дат горизонта достаются
        из той же таблицы фаз по дню года.
        """
        horizon_days = self._settings.forecast_horizon_days
        if not samples:
            return _empty_forecast("нет наблюдений для прогноза")

        last_date = max(sample.date for sample in samples)
        norms: dict[date, tuple[float, float]] = {}
        for day in _days_after(last_date, horizon_days):
            point = climatology.estimate(phase_of(day))
            if point is not None:
                norms[day] = (point.mean, point.std)

        # Прогноз погоды — контекст для модели. Его отсутствие не блокирует расчёт.
        weather = chain.fetch_weather_forecast(
            context.centroid[0], context.centroid[1], horizon_days
        )
        return _call_model(
            lambda: client.forecast(
                ForecastRequest(
                    polygon_id=str(context.field_id),
                    observations=[
                        SeriesPoint(date=sample.date, primary_ndvi=sample.ndvi)
                        for sample in samples
                    ],
                    horizon_days=horizon_days,
                    sowing_date=context.sowing_date,
                    weather_forecast=[
                        WeatherPoint(
                            date=item.date,
                            temperature=item.temperature,
                            precipitation=item.precipitation,
                        )
                        for item in weather.items
                    ],
                    climatology=norms,
                )
            )
        )

    def _assess_risk(
        self,
        context: AnalysisContext,
        periods: list[AnomalyPeriod],
        zscores: dict[date, float],
        in_period: list[SeriesSample],
        climatology: Climatology,
    ) -> RiskAssessment:
        restored_in_period = sum(
            1 for sample in in_period if sample.value_type == ValueType.RESTORED
        )
        valid_fractions = context.valid_fractions
        return risk_module.assess(
            anomalies=periods,
            # В оценку идут z-score, а не сырые значения: см. analytics/risk.py
            recent_zscores=list(zscores.items()),
            observed_count=sum(
                1 for sample in in_period if sample.value_type == ValueType.OBSERVED
            ),
            mean_valid_fraction=(
                sum(valid_fractions) / len(valid_fractions) if valid_fractions else None
            ),
            restored_fraction=(restored_in_period / len(in_period)) if in_period else 0.0,
            climatology_available=climatology.available,
        )

    # ------------------------------------------------------------------
    # Запись результатов
    # ------------------------------------------------------------------

    def _store_analysis(self, context: AnalysisContext, outcome: AnalysisOutcome) -> None:
        """Записать все результаты анализа одной транзакцией.

        Раньше восстановленные значения, аномалии и прогноз писались тремя
        независимыми транзакциями, и падение посередине оставляло поле с
        новым рядом, но старыми аномалиями. Теперь либо обновляется всё,
        либо ничего.
        """
        with unit_of_work() as uow:
            uow.observations.replace_restored(
                context.field_id,
                _restored_rows(
                    context.field_id,
                    outcome.restored,
                    context.weather_by_date,
                    outcome.restored_source,
                ),
            )
            uow.observations.set_climatology(
                context.field_id, outcome.zscores, outcome.norm_bands
            )
            uow.radar.set_derived(context.field_id, outcome.radar_derived)
            uow.anomalies.replace_for_field(
                context.field_id,
                [_to_anomaly(context.field_id, period) for period in outcome.periods],
            )
            uow.forecasts.replace_for_field(
                context.field_id, _to_forecast_run(context.field_id, outcome.forecast)
            )
            uow.observations.replace_forecast(
                context.field_id, _forecast_rows(context.field_id, outcome.forecast)
            )

            field = uow.fields.get(context.field_id)
            if field is not None:
                _apply_assessment(field, outcome)

    def _report_visualization(self, context: AnalysisContext) -> None:
        """Отметить стадию визуализации.

        Слои снимков добавляются позже, но стадия существует в интерфейсе,
        и без отметки список стадий выглядел бы незавершённым.
        """
        with self._stage(
            context.project_id, context.field_id, PipelineStage.VISUALIZATION
        ) as stage:
            stage.message("данные готовы к отображению", 1.0)

    # ------------------------------------------------------------------
    # Конечное состояние ошибки
    # ------------------------------------------------------------------

    def mark_failed(self, field_id: uuid.UUID, error_code: str) -> None:
        """Зафиксировать окончательную неудачу обработки.

        Без этого поле, упавшее на середине пайплайна, навсегда осталось бы
        в статусе `pending`, и пользователь ждал бы результата, которого
        не будет. Наружу уходит только код ошибки: подробности остаются
        в логах, потому что текст исключения может раскрывать внутреннее
        устройство сервиса.
        """
        project_id: uuid.UUID | None = None
        try:
            with unit_of_work() as uow:
                field = uow.fields.get(field_id)
                if field is None:
                    return
                project_id = field.project_id
                field.status = FieldStatus.FAILED
                field.data_quality = {**(field.data_quality or {}), "last_error": error_code}
        except Exception:
            # Отдельно логируем: если и это не удалось, диагностировать
            # застрявшее поле придётся по логам задачи.
            logger.exception("field_mark_failed_error", extra={"field_id": str(field_id)})
            return

        # Поле завершилось — пусть и неудачно. Без этого события интерфейс
        # считает его всё ещё обрабатывающимся: полоса прогресса не доходит
        # до конца, а оценка оставшегося времени не исчезает никогда.
        if project_id is not None:
            progress.field_finished(
                project_id, field_id, FieldStatus.FAILED.value, {"error": error_code}
            )

    # ------------------------------------------------------------------

    def _resolve_ml_client(self) -> MLClient:
        return self._ml_client if self._ml_client is not None else get_client()

    def _stage(
        self, project_id: uuid.UUID, field_id: uuid.UUID, stage: PipelineStage
    ) -> progress.StageTracker:
        return progress.StageTracker(project_id, field_id, stage, task_id=self._task_id)

    @staticmethod
    def _require_field(uow: UnitOfWork, field_id: uuid.UUID) -> Field:
        field = uow.fields.get_with_project(field_id)
        if field is None:
            raise FieldMissing(str(field_id))
        return field


# ----------------------------------------------------------------------
# Преобразование расчётов в строки таблиц
# ----------------------------------------------------------------------


def _to_radar_sample(row) -> RadarSample:
    return RadarSample(
        date=row.date,
        orbit_direction=row.orbit_direction,
        relative_orbit=row.relative_orbit,
        vv_median_db=row.vv_median_db,
        vh_median_db=row.vh_median_db,
        rvi_median=row.rvi_median,
        vh_vv_difference_db=row.vh_vv_difference_db,
        spatial_iqr_db=row.spatial_iqr_db,
        low_signal_fraction=row.low_signal_fraction,
        valid_fraction=row.valid_fraction,
    )


def _apply_corroboration(
    period: AnomalyPeriod,
    context: AnalysisContext,
    in_period: list[SeriesSample],
    samples: list[RadarSample],
    events: list[radar_module.RadarEvent],
) -> None:
    """Дописать в аномалию оценку подтверждённости независимыми источниками.

    Результат кладётся в `factors`, потому что оттуда он уезжает в API и отчёт
    без отдельного преобразования, и дублируется отдельной колонкой — по ней
    аномалии можно отбирать запросом, не разбирая JSON.
    """
    clouds = [
        value
        for day, value in context.cloud_by_date.items()
        if period.start_date <= day <= period.end_date
    ]
    observed_points = sum(
        1
        for sample in in_period
        if period.start_date <= sample.date <= period.end_date
        and sample.value_type == ValueType.OBSERVED
    )

    result = radar_module.corroborate(
        start_date=period.start_date,
        end_date=period.end_date,
        observed_points=observed_points,
        restored_fraction=period.restored_fraction,
        cloud_fraction=sum(clouds) / len(clouds) if clouds else None,
        weather_hypotheses=period.factors.get("hypotheses") or [],
        samples=samples,
        events=events,
    )

    period.factors["corroboration"] = result.score
    period.factors["corroboration_level"] = result.level
    period.factors["corroboration_parts"] = result.parts
    period.factors["corroboration_notes"] = result.notes


def _radar_rows(field_id: uuid.UUID, items: list) -> list[dict]:
    """Строки радарных наблюдений.

    Производные величины здесь не заполняются: они зависят от всего ряда
    целиком и считаются на стадии анализа, когда ряд собран.
    """
    return [
        {
            "field_id": field_id,
            "date": item.date,
            "source": item.source,
            "orbit_direction": item.orbit_direction,
            "relative_orbit": item.relative_orbit,
            "vv_median_db": item.vv_median_db,
            "vh_median_db": item.vh_median_db,
            "vh_vv_difference_db": item.vh_vv_difference_db,
            "rvi_median": item.rvi_median,
            "spatial_iqr_db": item.spatial_iqr_db,
            "low_signal_fraction": item.low_signal_fraction,
            "valid_fraction": item.valid_fraction,
            "scene_id": item.scene_id,
            "missing_reason": item.missing_reason,
        }
        for item in items
    ]


def _observation_rows(field_id: uuid.UUID, satellite: list, weather: list) -> list[dict]:
    """Строки наблюдений, сшитые с погодой по дате."""
    weather_by_date = {item.date: item for item in weather}
    return [
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
            "temperature": _weather_field(weather_by_date.get(item.date), "temperature"),
            "precipitation": _weather_field(weather_by_date.get(item.date), "precipitation"),
        }
        for item in satellite
    ]


def _weather_field(observation, attribute: str) -> float | None:
    return getattr(observation, attribute) if observation is not None else None


def _restored_rows(
    field_id: uuid.UUID,
    predictions: list[Prediction],
    weather_by_date: dict[date, tuple[float | None, float | None]],
    source: str,
) -> list[dict]:
    rows = []
    for item in predictions:
        temperature, precipitation = weather_by_date.get(item.date) or _NO_WEATHER
        rows.append(
            {
                "field_id": field_id,
                "date": item.date,
                "value_type": ValueType.RESTORED,
                "source": source,
                "ndvi_mean": item.value,
                "confidence": item.confidence,
                "temperature": temperature,
                "precipitation": precipitation,
            }
        )
    return rows


def _forecast_rows(field_id: uuid.UUID, forecast: ForecastResult) -> list[dict]:
    return [
        {
            "field_id": field_id,
            "date": point.date,
            "value_type": ValueType.FORECAST,
            "source": forecast.source,
            "ndvi_mean": point.value,
            "ndvi_lo": point.low,
            "ndvi_hi": point.high,
            "confidence": forecast.confidence,
        }
        for point in forecast.points
    ]


def _to_anomaly(field_id: uuid.UUID, period: AnomalyPeriod) -> Anomaly:
    return Anomaly(
        field_id=field_id,
        start_date=period.start_date,
        end_date=period.end_date,
        duration_days=period.duration_days,
        severity=period.severity,
        max_zscore=period.max_zscore,
        mean_zscore=period.mean_zscore,
        restored_fraction=period.restored_fraction,
        confidence=period.confidence,
        corroboration=period.factors.get("corroboration"),
        factors=period.factors,
    )


def _norm_bands(
    climatology: Climatology, in_period: list[SeriesSample]
) -> dict[date, tuple[float, float]]:
    """Коридор нормы на датах периода анализа.

    Границы — медиана плюс-минус одно стандартное отклонение, то есть ровно
    тот порог, начиная с которого отклонение считается угнетением (z = −1).
    Благодаря этому линия коридора на графике и найденные аномалии не спорят
    друг с другом.
    """
    bands: dict[date, tuple[float, float]] = {}
    if not climatology.available:
        return bands

    for sample in in_period:
        point = climatology.estimate(phase_of(sample.date))
        if point is None:
            continue
        bands[sample.date] = (
            round(point.mean - point.std, 6),
            round(point.mean + point.std, 6),
        )
    return bands


def _to_forecast_run(field_id: uuid.UUID, forecast: ForecastResult) -> ForecastRun:
    return ForecastRun(
        field_id=field_id,
        horizon_days=len(forecast.points),
        model_version=forecast.model_version,
        direction=forecast.direction,
        risk_level=forecast.risk_level,
        confidence=forecast.confidence,
        insufficient_reason=forecast.insufficient_reason,
        factors=forecast.factors,
    )


def _apply_assessment(field: Field, outcome: AnalysisOutcome) -> None:
    """Перенести оценку риска на поле.

    Вместе с баллом сохраняется разложение по факторам: пользователь должен
    видеть, из чего сложилась оценка, а не только итоговое число.
    """
    assessment = outcome.assessment
    climatology = outcome.climatology

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


# ----------------------------------------------------------------------
# Вспомогательное
# ----------------------------------------------------------------------


def _build_samples(
    context: AnalysisContext, restored: list[Prediction]
) -> list[SeriesSample]:
    """Собрать ряд для анализа: наблюдения и восстановленные значения.

    Происхождение значения сохраняется в `value_type` и доходит до вывода:
    аномалия, опирающаяся на интерполяцию, обязана иметь меньшую уверенность,
    чем аномалия по фактическим снимкам.
    """

    def sample(day: date, value: float, value_type: ValueType) -> SeriesSample:
        temperature, precipitation = context.weather_by_date.get(day) or _NO_WEATHER
        return SeriesSample(
            date=day,
            ndvi=value,
            value_type=value_type,
            ndmi=context.ndmi_by_date.get(day),
            temperature=temperature,
            precipitation=precipitation,
        )

    return [sample(day, value, ValueType.OBSERVED) for day, value in context.observed] + [
        sample(item.date, item.value, ValueType.RESTORED) for item in restored
    ]


def _days_between(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def _days_after(start: date, count: int) -> list[date]:
    return [start + timedelta(days=offset) for offset in range(1, count + 1)]


def _empty_forecast(reason: str) -> ForecastResult:
    """Пустой прогноз с указанием причины.

    Отсутствие прогноза честнее выдуманного, поэтому причина обязательна
    и показывается пользователю.
    """
    return ForecastResult(
        points=[], model_version="none", source="none", insufficient_reason=reason
    )


def _call_model[T](call) -> T:
    """Обратиться к сервису моделей, переведя отказ в повторяемую ошибку."""
    try:
        return call()
    except UpstreamError as exc:
        raise TransientPipelineError(f"сервис моделей не ответил: {exc}") from exc


def _no_data_error(result, message: str) -> Exception:
    """Выбрать между повторяемой и окончательной ошибкой сбора.

    Пустой период данными не наполнится: повторять задачу бессмысленно,
    и поле сразу получает конечный статус. Отказ источника, наоборот,
    имеет смысл повторить.
    """
    detail = "; ".join(result.errors) or message
    if result.is_permanently_empty:
        return InsufficientDataError(detail)
    return TransientPipelineError(detail)
