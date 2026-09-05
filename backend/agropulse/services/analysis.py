"""Сценарии чтения результатов анализа: аномалии, риск, сводка, реестр.

Два уровня агрегации, и они отвечают на разные вопросы. Сводка по проекту —
вопрос агронома «какие поля проверить в первую очередь». Реестр хозяйств —
вопрос распорядителя средств «кого рассматривать первым»; там единицей
решения становится хозяйство, потому что поддержка выдаётся ему, а не контуру.

Общее у обоих одно правило: участок с недостаточными данными искусственного
балла не получает и выносится отдельно. Выдуманная оценка выглядит как знание.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date

from agropulse.analytics import farm as farm_module
from agropulse.analytics import radar as radar_module
from agropulse.analytics.farm import FarmAssessment
from agropulse.analytics.radar import RadarSample
from agropulse.db.models import (
    Anomaly,
    Farm,
    Field,
    FieldStatus,
    ForecastRun,
    Observation,
    RadarObservation,
    ValueType,
)
from agropulse.db.uow import UnitOfWork
from agropulse.errors import FarmNotFoundError, FieldNotFoundError, ProjectNotFoundError


@dataclass(slots=True)
class RiskView:
    """Составной риск поля с раскрытием вклада факторов."""

    field_id: uuid.UUID
    status: FieldStatus
    score: float | None
    breakdown: dict | None
    explanation: list[str]
    confidence: float | None
    insufficient_reason: str | None
    climatology: dict | None


@dataclass(slots=True)
class RadarSeriesView:
    """Радарный ряд поля вместе с найденными в нём событиями."""

    field_id: uuid.UUID
    source: str | None
    points: list[RadarObservation]
    events: list[radar_module.RadarEvent] = dataclass_field(default_factory=list)


@dataclass(slots=True)
class FieldSummaryView:
    field_id: uuid.UUID
    name: str
    area_ha: float | None
    crop: str | None
    status: FieldStatus
    risk_score: float | None
    anomalies_count: int
    worst_anomaly: Anomaly | None
    observed_points: int
    restored_points: int
    mean_valid_fraction: float | None
    inspection_rank: int | None = None


@dataclass(slots=True)
class ProjectSummaryView:
    project_id: uuid.UUID
    period_from: date
    period_to: date
    total_fields: int
    critical: int
    attention: int
    normal: int
    insufficient_data: int
    fields: list[FieldSummaryView] = dataclass_field(default_factory=list)


@dataclass(slots=True)
class FarmSummaryView:
    """Хозяйство целиком: индекс, достоверность и его поля."""

    farm: Farm
    period_from: date
    period_to: date
    assessment: FarmAssessment
    fields: list[FieldSummaryView] = dataclass_field(default_factory=list)


@dataclass(slots=True)
class RegistryRowView:
    farm: Farm
    assessment: FarmAssessment
    # Место в очереди на рассмотрение. У хозяйства без заключения его нет:
    # номер в реестре означает приоритет, а не порядок в списке.
    rank: int | None = None


@dataclass(slots=True)
class RegistryView:
    """Реестр приоритетной поддержки по всем хозяйствам проекта.

    Три списка, а не один с сортировкой. Хозяйства без заключения нельзя
    поставить в конец очереди: это прочиталось бы как «поддержка не нужна»,
    тогда как сказать про них нечего. Поля без хозяйства не попадают ни в одну
    строку реестра вовсе, и это видно, а не спрятано.
    """

    project_id: uuid.UUID
    period_from: date
    period_to: date
    rows: list[RegistryRowView] = dataclass_field(default_factory=list)
    undetermined: list[RegistryRowView] = dataclass_field(default_factory=list)
    unassigned_fields: list[FieldSummaryView] = dataclass_field(default_factory=list)

    @property
    def farms_total(self) -> int:
        return len(self.rows) + len(self.undetermined)

    @property
    def total_area_ha(self) -> float:
        rows = self.rows + self.undetermined
        return round(sum(row.assessment.total_area_ha for row in rows), 1)


class AnalysisService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def anomalies(self, field_id: uuid.UUID) -> list[Anomaly]:
        """Аномальные периоды поля, самые тяжёлые первыми."""
        self._require_field(field_id)
        return self._uow.anomalies.list_for_field(field_id)

    def risk(self, field_id: uuid.UUID) -> RiskView:
        field = self._require_field(field_id)
        breakdown = field.risk_breakdown or {}
        return RiskView(
            field_id=field.id,
            status=field.status,
            score=field.risk_score,
            breakdown=breakdown.get("weights"),
            explanation=breakdown.get("explanation") or [],
            confidence=breakdown.get("confidence"),
            insufficient_reason=breakdown.get("insufficient_reason"),
            climatology=breakdown.get("climatology"),
        )

    def radar(self, field_id: uuid.UUID) -> RadarSeriesView:
        """Радарный ряд Sentinel-1 и резкие изменения в нём.

        События не хранятся отдельной таблицей: они однозначно выводятся из
        уже записанных производных величин, и лишняя таблица означала бы
        обязанность держать её в согласии с рядом при каждом пересчёте.
        """
        self._require_field(field_id)
        rows = self._uow.radar.list_for_field(field_id)
        if not rows:
            return RadarSeriesView(field_id=field_id, source=None, points=[])

        samples = [
            RadarSample(
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
            for row in rows
        ]
        derived = {
            row.date: {
                "vv_change_db": row.vv_change_db,
                "vh_change_db": row.vh_change_db,
                "rvi_change": row.rvi_change,
                "change_point_score": row.change_point_score,
            }
            for row in rows
            if row.vh_change_db is not None or row.vv_change_db is not None
        }
        return RadarSeriesView(
            field_id=field_id,
            source=rows[0].source,
            points=rows,
            events=radar_module.detect_events(samples, derived),
        )

    def forecast(self, field_id: uuid.UUID) -> ForecastRun | None:
        """Метаданные последнего прогноза поля.

        Отсутствие прогона — штатный ответ, а не ошибка: поле могло ещё не
        обрабатываться или данных не хватило на построение прогноза.
        """
        self._require_field(field_id)
        return self._uow.forecasts.get_for_field(field_id)

    def project_summary(self, project_id: uuid.UUID) -> ProjectSummaryView:
        """Сводка по проекту с очередью на осмотр.

        Аномалии и наблюдения всех полей читаются двумя запросами, а не
        двумя на каждое поле: на хозяйстве в сотню полей прежний вариант
        превращал открытие дашборда в две сотни обращений к базе.
        """
        project = self._uow.projects.get(project_id)
        if project is None:
            raise ProjectNotFoundError(project_id=str(project_id))

        fields = self._uow.fields.list_for_project(project_id)
        field_ids = [field.id for field in fields]
        anomalies_by_field = self._uow.anomalies.list_for_fields(field_ids)
        observations_by_field = self._uow.observations.list_for_fields(field_ids)

        summaries = [
            _summarize_field(
                field=field,
                anomalies=anomalies_by_field.get(field.id, []),
                observations=observations_by_field.get(field.id, []),
                period_from=project.period_from,
                period_to=project.period_to,
            )
            for field in fields
        ]

        return ProjectSummaryView(
            project_id=project.id,
            period_from=project.period_from,
            period_to=project.period_to,
            total_fields=len(summaries),
            critical=_count_status(summaries, FieldStatus.CRITICAL),
            attention=_count_status(summaries, FieldStatus.ATTENTION),
            normal=_count_status(summaries, FieldStatus.NORMAL),
            insufficient_data=_count_status(summaries, FieldStatus.INSUFFICIENT_DATA),
            fields=_rank(summaries),
        )

    def farm_summary(self, farm_id: uuid.UUID) -> FarmSummaryView:
        """Хозяйство целиком: индекс потребности в поддержке и очередь его полей.

        Индекс считается здесь, а не хранится на строке хозяйства. Он полностью
        выводится из баллов полей, и отдельное хранение завело бы третье место,
        где данные расходятся с расчётом, — при этом пересчитывать его дешевле,
        чем инвалидировать.
        """
        farm = self._uow.farms.get(farm_id)
        if farm is None:
            raise FarmNotFoundError(farm_id=str(farm_id))
        project = self._uow.projects.get(farm.project_id)
        if project is None:
            raise ProjectNotFoundError(project_id=str(farm.project_id))

        fields = self._uow.fields.list_for_farm(farm_id)
        field_ids = [field.id for field in fields]
        anomalies_by_field = self._uow.anomalies.list_for_fields(field_ids)
        observations_by_field = self._uow.observations.list_for_fields(field_ids)
        forecasts = self._uow.forecasts.get_for_fields(field_ids)

        summaries = _rank(
            [
                _summarize_field(
                    field=field,
                    anomalies=anomalies_by_field.get(field.id, []),
                    observations=observations_by_field.get(field.id, []),
                    period_from=project.period_from,
                    period_to=project.period_to,
                )
                for field in fields
            ]
        )

        assessment = farm_module.assess(
            [
                farm_module.field_input(
                    field, anomalies_by_field.get(field.id, []), forecasts.get(field.id)
                )
                for field in fields
            ]
        )

        return FarmSummaryView(
            farm=farm,
            period_from=project.period_from,
            period_to=project.period_to,
            assessment=assessment,
            fields=summaries,
        )

    def project_registry(self, project_id: uuid.UUID) -> RegistryView:
        """Реестр хозяйств проекта, ранжированный по потребности в поддержке.

        Аномалии и прогнозы всех полей читаются двумя запросами. Наблюдения —
        только по полям без хозяйства: в строке реестра их не видно, они нужны
        лишь для того, чтобы объяснить каждое непривязанное поле по отдельности.
        """
        project = self._uow.projects.get(project_id)
        if project is None:
            raise ProjectNotFoundError(project_id=str(project_id))

        farms = self._uow.farms.list_for_project(project_id)
        fields = self._uow.fields.list_for_project(project_id)
        anomalies_by_field = self._uow.anomalies.list_for_fields([f.id for f in fields])
        forecasts = self._uow.forecasts.get_for_fields([f.id for f in fields])

        by_farm: dict[uuid.UUID, list[Field]] = {farm.id: [] for farm in farms}
        unassigned: list[Field] = []
        for field in fields:
            if field.farm_id in by_farm:
                by_farm[field.farm_id].append(field)
            else:
                unassigned.append(field)

        rows = [
            RegistryRowView(
                farm=farm,
                assessment=farm_module.assess(
                    [
                        farm_module.field_input(
                            field,
                            anomalies_by_field.get(field.id, []),
                            forecasts.get(field.id),
                        )
                        for field in by_farm[farm.id]
                    ]
                ),
            )
            for farm in farms
        ]

        # Заключение выдано — в очередь с номером; не выдано — в отдельный
        # список без номера. Смешивать их сортировкой нельзя: последнее место
        # в очереди читается как «проверять не нужно».
        ranked = sorted(
            (row for row in rows if row.assessment.support_need_score is not None
             and row.assessment.category is not farm_module.ReviewCategory.UNDETERMINED),
            key=lambda row: row.assessment.support_need_score or 0.0,
            reverse=True,
        )
        for position, row in enumerate(ranked, start=1):
            row.rank = position
        undetermined = [row for row in rows if row.rank is None]

        unassigned_observations = self._uow.observations.list_for_fields(
            [field.id for field in unassigned]
        )
        return RegistryView(
            project_id=project.id,
            period_from=project.period_from,
            period_to=project.period_to,
            rows=ranked,
            undetermined=undetermined,
            unassigned_fields=[
                _summarize_field(
                    field=field,
                    anomalies=anomalies_by_field.get(field.id, []),
                    observations=unassigned_observations.get(field.id, []),
                    period_from=project.period_from,
                    period_to=project.period_to,
                )
                for field in unassigned
            ],
        )

    def _require_field(self, field_id: uuid.UUID) -> Field:
        field = self._uow.fields.get(field_id)
        if field is None:
            raise FieldNotFoundError(field_id=str(field_id))
        return field


def _summarize_field(
    *,
    field: Field,
    anomalies: list[Anomaly],
    observations: list[Observation],
    period_from: date,
    period_to: date,
) -> FieldSummaryView:
    in_period = [o for o in observations if period_from <= o.date <= period_to]
    observed = [
        o for o in in_period if o.value_type == ValueType.OBSERVED and o.ndvi_mean
    ]
    valid_fractions = [o.valid_fraction for o in observed if o.valid_fraction is not None]

    return FieldSummaryView(
        field_id=field.id,
        name=field.name,
        area_ha=field.area_ha,
        crop=field.crop,
        status=field.status,
        risk_score=field.risk_score,
        anomalies_count=len(anomalies),
        worst_anomaly=anomalies[0] if anomalies else None,
        observed_points=len(observed),
        restored_points=sum(1 for o in in_period if o.value_type == ValueType.RESTORED),
        mean_valid_fraction=(
            round(sum(valid_fractions) / len(valid_fractions), 4) if valid_fractions else None
        ),
    )


def _count_status(summaries: list[FieldSummaryView], status: FieldStatus) -> int:
    return sum(1 for summary in summaries if summary.status == status)


def _rank(summaries: list[FieldSummaryView]) -> list[FieldSummaryView]:
    """Расставить поля по очереди на осмотр.

    Сначала поля с рассчитанным риском по убыванию балла, следом — участки
    без достаточных данных, без номера в очереди.
    """
    ranked = sorted(
        (summary for summary in summaries if summary.risk_score is not None),
        key=lambda summary: summary.risk_score or 0.0,
        reverse=True,
    )
    for position, summary in enumerate(ranked, start=1):
        summary.inspection_rank = position
    return ranked + [summary for summary in summaries if summary.risk_score is None]
