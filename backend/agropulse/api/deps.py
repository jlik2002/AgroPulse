"""Зависимости FastAPI: сборка сервисов на время запроса.

Всё, что нужно роутеру, приезжает сюда через `Depends`. Роутер не создаёт
ни сессий, ни клиентов внешних систем: их время жизни определяется здесь,
а в тесте любую из зависимостей можно подменить через `dependency_overrides`.

Сервисы собираются на каждый запрос, потому что у каждого запроса собственная
сессия базы. Клиенты внешних API состояния не имеют и создаются рядом.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from agropulse.api.identity import get_owner_id
from agropulse.config import Settings, get_settings
from agropulse.db.session import get_db
from agropulse.db.uow import UnitOfWork
from agropulse.services.analysis import AnalysisService
from agropulse.services.farms import FarmService
from agropulse.services.fields import FieldService
from agropulse.services.projects import ProjectService
from agropulse.services.reports import ReportService
from agropulse.services.territory import TerritoryService
from agropulse.tasks.publisher import CeleryTaskPublisher, TaskPublisher

SessionDep = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
# Анонимный посетитель. Значение приходит из cookie, см. `api/identity.py`.
OwnerIdDep = Annotated[uuid.UUID, Depends(get_owner_id)]


def get_uow(session: SessionDep) -> UnitOfWork:
    return UnitOfWork(session)


UnitOfWorkDep = Annotated[UnitOfWork, Depends(get_uow)]


def get_task_publisher() -> TaskPublisher:
    return CeleryTaskPublisher()


TaskPublisherDep = Annotated[TaskPublisher, Depends(get_task_publisher)]


def get_project_service(uow: UnitOfWorkDep) -> ProjectService:
    return ProjectService(uow)


def get_farm_service(uow: UnitOfWorkDep) -> FarmService:
    return FarmService(uow)


def get_field_service(uow: UnitOfWorkDep, publisher: TaskPublisherDep) -> FieldService:
    return FieldService(uow, publisher)


def get_analysis_service(uow: UnitOfWorkDep) -> AnalysisService:
    return AnalysisService(uow)


def get_report_service(uow: UnitOfWorkDep) -> ReportService:
    return ReportService(uow)


def get_territory_service() -> TerritoryService:
    return TerritoryService()


ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]
FarmServiceDep = Annotated[FarmService, Depends(get_farm_service)]
FieldServiceDep = Annotated[FieldService, Depends(get_field_service)]
AnalysisServiceDep = Annotated[AnalysisService, Depends(get_analysis_service)]
ReportServiceDep = Annotated[ReportService, Depends(get_report_service)]
TerritoryServiceDep = Annotated[TerritoryService, Depends(get_territory_service)]
