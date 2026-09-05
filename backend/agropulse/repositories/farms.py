"""Хранение хозяйств."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from agropulse.db.models import Farm


class FarmRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, farm_id: uuid.UUID) -> Farm | None:
        return self._session.get(Farm, farm_id)

    def list_for_project(self, project_id: uuid.UUID) -> list[Farm]:
        """Хозяйства проекта в алфавитном порядке.

        Порядок по названию, а не по дате создания: реестр ранжирует
        хозяйства сам, а всюду, где показывается просто список — выбор
        хозяйства для поля, фильтр — человек ищет глазами по имени.
        """
        return list(
            self._session.scalars(
                select(Farm).where(Farm.project_id == project_id).order_by(Farm.name)
            ).all()
        )

    def find_by_name(self, project_id: uuid.UUID, name: str) -> Farm | None:
        """Хозяйство с таким названием в проекте.

        Нужно, чтобы вернуть человеку внятную ошибку вместо нарушения
        уникального ключа: имя вводится руками, и совпадение — обычное дело.
        """
        return self._session.scalar(
            select(Farm).where(Farm.project_id == project_id, Farm.name == name)
        )

    def add(self, farm: Farm) -> Farm:
        self._session.add(farm)
        # flush, а не commit: идентификатор нужен сразу, завершение
        # транзакции остаётся за сервисом.
        self._session.flush()
        return farm

    def delete(self, farm: Farm) -> None:
        self._session.delete(farm)
