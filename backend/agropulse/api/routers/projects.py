"""Эндпоинты проекта — анонимного рабочего пространства."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from agropulse.db.models import Project
from agropulse.db.session import get_db
from agropulse.schemas.project import ProjectCreate, ProjectRead

router = APIRouter(prefix="/projects", tags=["projects"])


def get_project_or_404(project_id: uuid.UUID, db: Session) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="проект не найден")
    return project


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> Project:
    """Создать проект. Регистрация не требуется — идентификатор хранит клиент."""
    project = Project(
        name=payload.name,
        period_from=payload.period_from,
        period_to=payload.period_to,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectRead)
def read_project(project_id: uuid.UUID, db: Session = Depends(get_db)) -> Project:
    return get_project_or_404(project_id, db)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    project = get_project_or_404(project_id, db)
    db.delete(project)
    db.commit()
