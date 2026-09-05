"""Эндпоинты полей: добавление, редактирование, удаление, запуск обработки.

Поле — центральная сущность продукта, поэтому управление контурами вынесено
в отдельный ресурс со своим жизненным циклом, а не спрятано внутрь проекта.
"""

import uuid

from fastapi import APIRouter, status

from agropulse.api.deps import FieldServiceDep
from agropulse.schemas.field import (
    FieldCreate,
    FieldRead,
    FieldUpdate,
    TimeseriesRead,
)
from agropulse.services.fields import CreateFieldCommand, UpdateFieldCommand

router = APIRouter(tags=["fields"])


@router.post(
    "/projects/{project_id}/fields",
    response_model=FieldRead,
    status_code=status.HTTP_201_CREATED,
)
def create_field(
    project_id: uuid.UUID, payload: FieldCreate, service: FieldServiceDep
) -> FieldRead:
    """Добавить поле в проект.

    Полигон приходит либо нарисованным вручную, либо выбранным из открытого
    источника контуров — различие сохраняется в поле `source`.
    """
    field = service.create(
        project_id,
        CreateFieldCommand(
            name=payload.name,
            geometry=payload.geometry.model_dump(),
            crop=payload.crop,
            sowing_date=payload.sowing_date,
            source=payload.source,
            external_ref=payload.external_ref,
        ),
    )
    return FieldRead.from_model(field)


@router.get("/projects/{project_id}/fields", response_model=list[FieldRead])
def list_fields(project_id: uuid.UUID, service: FieldServiceDep) -> list[FieldRead]:
    return [FieldRead.from_model(field) for field in service.list_for_project(project_id)]


@router.get("/fields/{field_id}", response_model=FieldRead)
def read_field(field_id: uuid.UUID, service: FieldServiceDep) -> FieldRead:
    return FieldRead.from_model(service.get(field_id))


@router.patch("/fields/{field_id}", response_model=FieldRead)
def update_field(
    field_id: uuid.UUID, payload: FieldUpdate, service: FieldServiceDep
) -> FieldRead:
    field = service.update(
        field_id,
        UpdateFieldCommand(
            name=payload.name,
            geometry=payload.geometry.model_dump() if payload.geometry else None,
            crop=payload.crop,
            sowing_date=payload.sowing_date,
        ),
    )
    return FieldRead.from_model(field)


@router.delete("/fields/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_field(field_id: uuid.UUID, service: FieldServiceDep) -> None:
    service.delete(field_id)


@router.get("/fields/{field_id}/timeseries", response_model=TimeseriesRead)
def read_timeseries(field_id: uuid.UUID, service: FieldServiceDep) -> TimeseriesRead:
    """Временной ряд поля со сводкой качества данных."""
    return TimeseriesRead.from_view(service.timeseries(field_id))


@router.post("/fields/{field_id}/process", status_code=status.HTTP_202_ACCEPTED)
def start_processing(field_id: uuid.UUID, service: FieldServiceDep) -> dict:
    """Поставить полную обработку поля в очередь.

    Отвечаем сразу: обработка занимает минуты и выполняется воркером. Ход
    выполнения по стадиям доступен через поток событий проекта.
    """
    accepted = service.request_processing(field_id)
    return {"field_id": str(accepted.field_id), "task_id": accepted.task_id}


@router.post("/projects/{project_id}/process", status_code=status.HTTP_202_ACCEPTED)
def start_project_processing(project_id: uuid.UUID, service: FieldServiceDep) -> dict:
    """Поставить обработку всех полей проекта."""
    accepted = service.request_project_processing(project_id)
    return {
        "project_id": str(project_id),
        "tasks": [
            {"field_id": str(item.field_id), "task_id": item.task_id} for item in accepted
        ],
    }
