"""Хранение проектов."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from agropulse.db.models import Project

# Сколько проектов возвращаем владельцу. Список нужен, чтобы вернуться
# к работе, а не чтобы листать архив за всё время.
OWNER_PROJECTS_LIMIT = 20


class ProjectRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, project_id: uuid.UUID) -> Project | None:
        return self._session.get(Project, project_id)

    def list_for_owner(self, owner_id: uuid.UUID) -> list[Project]:
        """Проекты посетителя, свежие первыми."""
        rows = self._session.execute(
            select(Project)
            .where(Project.owner_id == owner_id)
            .order_by(Project.created_at.desc())
            .limit(OWNER_PROJECTS_LIMIT)
        )
        return list(rows.scalars())

    def exists(self, project_id: uuid.UUID) -> bool:
        return self.get(project_id) is not None

    def add(self, project: Project) -> Project:
        self._session.add(project)
        # flush, а не commit: идентификатор нужен сразу, а завершение
        # транзакции остаётся за сервисом.
        self._session.flush()
        return project

    def delete(self, project: Project) -> None:
        self._session.delete(project)
