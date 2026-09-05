"""Хранение хозяйств.

Справочник общий: хозяйство не принадлежит проекту, потому что его название,
ИНН и район не зависят от периода наблюдения. Отбор по проекту происходит
не здесь, а там, где считается заключение, — через поля хозяйства.
"""

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

    def list_all(self) -> list[Farm]:
        """Весь справочник по алфавиту.

        Порядок по названию, а не по дате создания: реестр ранжирует хозяйства
        сам, а там, где показывается просто список — выбор хозяйства для поля,
        фильтр — человек ищет глазами по имени.
        """
        return list(self._session.scalars(select(Farm).order_by(Farm.name)).all())

    def find_by_name(self, name: str) -> Farm | None:
        """Хозяйство с таким названием.

        Нужно, чтобы вернуть человеку внятную ошибку вместо нарушения
        уникального ключа: имя вводится руками, и совпадение — обычное дело.
        """
        return self._session.scalar(select(Farm).where(Farm.name == name))

    def add(self, farm: Farm) -> Farm:
        self._session.add(farm)
        # flush, а не commit: идентификатор нужен сразу, завершение
        # транзакции остаётся за сервисом.
        self._session.flush()
        return farm

    def delete(self, farm: Farm) -> None:
        self._session.delete(farm)
