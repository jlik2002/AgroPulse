"""Результаты анализа: аномалии, риск и сводка по проекту.

Сводка — главный экран для руководителя: она отвечает на вопрос «какие поля
проверить в первую очередь». Поэтому поля ранжируются по составному риску,
а участки с недостаточными данными выносятся отдельно и искусственного балла
не получают.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from agropulse.db.models import Anomaly, Field, FieldStatus, Observation, Project, ValueType
from agropulse.db.session import get_db
from agropulse.schemas.analysis import (
    AnomalyRead,
    FieldSummary,
    ProjectSummary,
    RiskRead,
)

router = APIRouter(tags=["analysis"])


@router.get("/fields/{field_id}/anomalies", response_model=list[AnomalyRead])
def read_anomalies(field_id: uuid.UUID, db: Session = Depends(get_db)) -> list[Anomaly]:
    """Аномальные периоды поля, самые тяжёлые первыми."""
    if db.get(Field, field_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="поле не найдено")
    return db.scalars(
        select(Anomaly)
        .where(Anomaly.field_id == field_id)
        .order_by(Anomaly.max_zscore, Anomaly.start_date)
    ).all()


@router.get("/fields/{field_id}/risk", response_model=RiskRead)
def read_risk(field_id: uuid.UUID, db: Session = Depends(get_db)) -> RiskRead:
    """Составной риск поля с раскрытием вклада факторов."""
    field = db.get(Field, field_id)
    if field is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="поле не найдено")

    breakdown = field.risk_breakdown or {}
    return RiskRead(
        field_id=field.id,
        status=field.status,
        score=field.risk_score,
        breakdown=breakdown.get("weights"),
        explanation=breakdown.get("explanation") or [],
        confidence=breakdown.get("confidence"),
        insufficient_reason=breakdown.get("insufficient_reason"),
        climatology=breakdown.get("climatology"),
    )


@router.get("/projects/{project_id}/summary", response_model=ProjectSummary)
def read_summary(project_id: uuid.UUID, db: Session = Depends(get_db)) -> ProjectSummary:
    """Сводка по проекту с очередью на осмотр."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="проект не найден")

    fields = db.scalars(select(Field).where(Field.project_id == project_id)).all()

    summaries: list[FieldSummary] = []
    for field in fields:
        anomalies = db.scalars(
            select(Anomaly)
            .where(Anomaly.field_id == field.id)
            .order_by(Anomaly.max_zscore)
        ).all()
        observations = db.scalars(
            select(Observation).where(Observation.field_id == field.id)
        ).all()

        in_period = [
            o for o in observations if project.period_from <= o.date <= project.period_to
        ]
        observed = [o for o in in_period if o.value_type == ValueType.OBSERVED and o.ndvi_mean]
        valid = [o.valid_fraction for o in observed if o.valid_fraction is not None]

        summaries.append(
            FieldSummary(
                field_id=field.id,
                name=field.name,
                area_ha=field.area_ha,
                crop=field.crop,
                status=field.status,
                risk_score=field.risk_score,
                anomalies_count=len(anomalies),
                worst_anomaly=(
                    AnomalyRead.model_validate(anomalies[0]) if anomalies else None
                ),
                observed_points=len(observed),
                restored_points=sum(
                    1 for o in in_period if o.value_type == ValueType.RESTORED
                ),
                mean_valid_fraction=(
                    round(sum(valid) / len(valid), 4) if valid else None
                ),
                inspection_rank=None,
            )
        )

    # Ранжирование: сначала поля с рассчитанным риском по убыванию балла,
    # следом — участки без достаточных данных, без номера в очереди.
    ranked = sorted(
        (s for s in summaries if s.risk_score is not None),
        key=lambda s: s.risk_score,
        reverse=True,
    )
    for position, item in enumerate(ranked, start=1):
        item.inspection_rank = position

    without_risk = [s for s in summaries if s.risk_score is None]

    return ProjectSummary(
        project_id=project.id,
        period_from=project.period_from,
        period_to=project.period_to,
        total_fields=len(summaries),
        critical=sum(1 for s in summaries if s.status == FieldStatus.CRITICAL),
        attention=sum(1 for s in summaries if s.status == FieldStatus.ATTENTION),
        normal=sum(1 for s in summaries if s.status == FieldStatus.NORMAL),
        insufficient_data=sum(
            1 for s in summaries if s.status == FieldStatus.INSUFFICIENT_DATA
        ),
        fields=ranked + without_risk,
    )
