"""Эндпоинты хозяйства и реестра приоритетной поддержки.

Справочник хозяйств общий: `/farms` не вложен в проект, потому что название,
ИНН и район предприятия не зависят от периода наблюдения. Заведённое однажды
хозяйство доступно из любого проекта.

Заключение — наоборот, вложено: `/projects/{id}/farms/{id}/summary`. Оценка
считается по периоду наблюдения, а он лежит на проекте, и одно предприятие
законно встречается в нескольких проектах с разными периодами.
"""

import uuid

from fastapi import APIRouter, status

from agropulse.api.deps import AnalysisServiceDep, FarmServiceDep
from agropulse.schemas.farm import (
    FarmCreate,
    FarmRead,
    FarmSummaryRead,
    FarmUpdate,
    RegistryRead,
)
from agropulse.services.farms import CreateFarmCommand, UpdateFarmCommand

router = APIRouter(tags=["farms"])


@router.post("/farms", response_model=FarmRead, status_code=status.HTTP_201_CREATED)
def create_farm(payload: FarmCreate, service: FarmServiceDep) -> FarmRead:
    """Завести хозяйство в общем справочнике."""
    farm = service.create(
        CreateFarmCommand(
            name=payload.name,
            inn=payload.inn,
            legal_form=payload.legal_form,
            district=payload.district,
            region=payload.region,
            contact=payload.contact,
            note=payload.note,
        )
    )
    return FarmRead.model_validate(farm)


@router.get("/farms", response_model=list[FarmRead])
def list_farms(service: FarmServiceDep) -> list[FarmRead]:
    """Весь справочник хозяйств, по алфавиту."""
    return [FarmRead.model_validate(farm) for farm in service.list_all()]


@router.get("/projects/{project_id}/registry", response_model=RegistryRead)
def read_registry(project_id: uuid.UUID, service: AnalysisServiceDep) -> RegistryRead:
    """Реестр хозяйств, ранжированный по индексу потребности в поддержке."""
    return RegistryRead.from_view(service.project_registry(project_id))


@router.get("/farms/{farm_id}", response_model=FarmRead)
def read_farm(farm_id: uuid.UUID, service: FarmServiceDep) -> FarmRead:
    return FarmRead.model_validate(service.get(farm_id))


@router.patch("/farms/{farm_id}", response_model=FarmRead)
def update_farm(
    farm_id: uuid.UUID, payload: FarmUpdate, service: FarmServiceDep
) -> FarmRead:
    farm = service.update(
        farm_id,
        UpdateFarmCommand(
            name=payload.name,
            inn=payload.inn,
            legal_form=payload.legal_form,
            district=payload.district,
            region=payload.region,
            contact=payload.contact,
            note=payload.note,
        ),
    )
    return FarmRead.model_validate(farm)


@router.delete("/farms/{farm_id}")
def delete_farm(farm_id: uuid.UUID, service: FarmServiceDep) -> dict:
    """Удалить хозяйство. Его поля остаются и теряют владельца.

    Ответ с телом, а не 204: интерфейс должен сказать, сколько полей осталось
    без хозяйства, иначе они молча пропадут из реестра.
    """
    return {"orphaned_fields": service.delete(farm_id)}


@router.get(
    "/projects/{project_id}/farms/{farm_id}/summary", response_model=FarmSummaryRead
)
def read_farm_summary(
    project_id: uuid.UUID, farm_id: uuid.UUID, service: AnalysisServiceDep
) -> FarmSummaryRead:
    """Индекс потребности в поддержке и очередь полей хозяйства.

    Считается по полям хозяйства внутри этого проекта: период наблюдения
    лежит на проекте, а справочник хозяйств общий.
    """
    return FarmSummaryRead.from_view(service.farm_summary(project_id, farm_id))
