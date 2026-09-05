"""Сценарии работы с проектом — анонимным рабочим пространством."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date

from agropulse.db.models import Project
from agropulse.db.uow import UnitOfWork
from agropulse.errors import ProjectNotFoundError

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CreateProjectCommand:
    name: str | None
    period_from: date
    period_to: date


class ProjectService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def create(self, command: CreateProjectCommand) -> Project:
        project = self._uow.projects.add(
            Project(
                name=command.name,
                period_from=command.period_from,
                period_to=command.period_to,
            )
        )
        self._uow.commit()
        logger.info("project_created", extra={"project_id": str(project.id)})
        return project

    def get(self, project_id: uuid.UUID) -> Project:
        project = self._uow.projects.get(project_id)
        if project is None:
            raise ProjectNotFoundError(project_id=str(project_id))
        return project

    def delete(self, project_id: uuid.UUID) -> None:
        """Удалить проект вместе со всеми полями и их данными.

        Каскад описан внешними ключами в схеме: поля, наблюдения, аномалии и
        прогресс уезжают одной транзакцией, а не серией запросов из Python.
        """
        project = self.get(project_id)
        self._uow.projects.delete(project)
        self._uow.commit()
        logger.info("project_deleted", extra={"project_id": str(project_id)})
