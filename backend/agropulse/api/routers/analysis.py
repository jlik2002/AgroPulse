"""Результаты анализа: аномалии, риск и сводка по проекту.

Сводка — главный экран для руководителя: она отвечает на вопрос «какие поля
проверить в первую очередь». Поэтому поля ранжируются по составному риску,
а участки с недостаточными данными выносятся отдельно и искусственного балла
не получают.
"""

import uuid

from fastapi import APIRouter

from agropulse.api.deps import AnalysisServiceDep
from agropulse.schemas.analysis import AnomalyRead, ProjectSummary, RiskRead

router = APIRouter(tags=["analysis"])


@router.get("/fields/{field_id}/anomalies", response_model=list[AnomalyRead])
def read_anomalies(field_id: uuid.UUID, service: AnalysisServiceDep) -> list[AnomalyRead]:
    """Аномальные периоды поля, самые тяжёлые первыми."""
    return [AnomalyRead.model_validate(anomaly) for anomaly in service.anomalies(field_id)]


@router.get("/fields/{field_id}/risk", response_model=RiskRead)
def read_risk(field_id: uuid.UUID, service: AnalysisServiceDep) -> RiskRead:
    """Составной риск поля с раскрытием вклада факторов."""
    return RiskRead.model_validate(service.risk(field_id))


@router.get("/projects/{project_id}/summary", response_model=ProjectSummary)
def read_summary(project_id: uuid.UUID, service: AnalysisServiceDep) -> ProjectSummary:
    """Сводка по проекту с очередью на осмотр."""
    return ProjectSummary.model_validate(service.project_summary(project_id))
