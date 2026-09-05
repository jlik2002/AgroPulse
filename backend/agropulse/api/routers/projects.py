"""Эндпоинты проекта — анонимного рабочего пространства."""

import uuid

from fastapi import APIRouter, status

from agropulse.api.deps import ProjectServiceDep
from agropulse.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate
from agropulse.services.projects import CreateProjectCommand, UpdateProjectCommand

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, service: ProjectServiceDep) -> ProjectRead:
    """Создать проект. Регистрация не требуется — идентификатор хранит клиент."""
    project = service.create(
        CreateProjectCommand(
            name=payload.name,
            period_from=payload.period_from,
            period_to=payload.period_to,
        )
    )
    return ProjectRead.model_validate(project)


@router.get("/{project_id}", response_model=ProjectRead)
def read_project(project_id: uuid.UUID, service: ProjectServiceDep) -> ProjectRead:
    return ProjectRead.model_validate(service.get(project_id))


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: uuid.UUID, payload: ProjectUpdate, service: ProjectServiceDep
) -> ProjectRead:
    """Изменить название или период анализа."""
    project = service.update(
        project_id,
        UpdateProjectCommand(
            name=payload.name,
            period_from=payload.period_from,
            period_to=payload.period_to,
        ),
    )
    return ProjectRead.model_validate(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: uuid.UUID, service: ProjectServiceDep) -> None:
    service.delete(project_id)
