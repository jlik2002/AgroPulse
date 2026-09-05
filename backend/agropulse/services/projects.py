"""Сценарии работы с проектом — анонимным рабочим пространством."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date

from agropulse.db.models import Project
from agropulse.db.uow import UnitOfWork
from agropulse.errors import InvalidPeriodError, ProjectNotFoundError

logger = logging.getLogger(__name__)


# Период короче двух недель даёт непоказательный ряд: на две-три съёмки
# климатологию не построить. Ограничение то же, что и при создании проекта.
MIN_PERIOD_DAYS = 14


@dataclass(slots=True)
class CreateProjectCommand:
    name: str | None
    period_from: date
    period_to: date


@dataclass(slots=True)
class UpdateProjectCommand:
    """Частичное обновление: `None` означает «не менять»."""

    name: str | None = None
    period_from: date | None = None
    period_to: date | None = None


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

    def update(self, project_id: uuid.UUID, command: UpdateProjectCommand) -> Project:
        """Изменить название или период проекта.

        Период общий для всех полей: только так результаты полей сопоставимы
        при ранжировании. Уже собранные наблюдения не удаляются — они лежат
        по датам, и следующий запуск дособерёт недостающее.
        """
        project = self.get(project_id)

        period_from = command.period_from or project.period_from
        period_to = command.period_to or project.period_to
        if (period_to - period_from).days < MIN_PERIOD_DAYS:
            raise InvalidPeriodError(
                period_from=str(period_from),
                period_to=str(period_to),
            )

        if command.name is not None:
            project.name = command.name
        project.period_from = period_from
        project.period_to = period_to

        self._uow.commit()
        logger.info("project_updated", extra={"project_id": str(project_id)})
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
