"""Хранение проектов."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from agropulse.db.models import Project


class ProjectRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, project_id: uuid.UUID) -> Project | None:
        return self._session.get(Project, project_id)

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
