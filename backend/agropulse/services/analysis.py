"""Сценарии чтения результатов анализа: аномалии, риск, сводка по проекту.

Сводка — главный экран для руководителя: она отвечает на вопрос «какие поля
проверить в первую очередь». Поэтому поля ранжируются по составному риску,
а участки с недостаточными данными выносятся отдельно и искусственного балла
не получают.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date

from agropulse.db.models import (
    Anomaly,
    Field,
    FieldStatus,
    ForecastRun,
    Observation,
    ValueType,
)
from agropulse.db.uow import UnitOfWork
from agropulse.errors import FieldNotFoundError, ProjectNotFoundError


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

        # Ранжирование: сначала поля с рассчитанным риском по убыванию балла,
        # следом — участки без достаточных данных, без номера в очереди.
        ranked = sorted(
            (summary for summary in summaries if summary.risk_score is not None),
            key=lambda summary: summary.risk_score,
            reverse=True,
        )
        for position, summary in enumerate(ranked, start=1):
            summary.inspection_rank = position
        without_risk = [summary for summary in summaries if summary.risk_score is None]

        return ProjectSummaryView(
            project_id=project.id,
            period_from=project.period_from,
            period_to=project.period_to,
            total_fields=len(summaries),
            critical=_count_status(summaries, FieldStatus.CRITICAL),
            attention=_count_status(summaries, FieldStatus.ATTENTION),
            normal=_count_status(summaries, FieldStatus.NORMAL),
            insufficient_data=_count_status(summaries, FieldStatus.INSUFFICIENT_DATA),
            fields=ranked + without_risk,
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
