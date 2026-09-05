"""Хранение полей."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from agropulse.db.models import Field


class FieldRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, field_id: uuid.UUID) -> Field | None:
        return self._session.get(Field, field_id)

    def get_with_project(self, field_id: uuid.UUID) -> Field | None:
        """Поле вместе с проектом.

        Период анализа хранится на проекте и нужен почти во всех сценариях
        чтения. Отдельный ленивый запрос за ним — лишний обход базы,
        поэтому проект подгружается тем же запросом.
        """
        return self._session.scalar(
            select(Field).options(joinedload(Field.project)).where(Field.id == field_id)
        )

    def list_for_project(self, project_id: uuid.UUID) -> list[Field]:
        return list(
            self._session.scalars(
                select(Field)
                .where(Field.project_id == project_id)
                .order_by(Field.created_at)
            ).all()
        )

    def list_for_farm(
        self, farm_id: uuid.UUID, project_id: uuid.UUID | None = None
    ) -> list[Field]:
        """Поля хозяйства, при необходимости — только внутри одного проекта.

        Отбор по проекту нужен всюду, где считается заключение: справочник
        хозяйств общий, и одно хозяйство может встречаться в нескольких
        проектах с разными периодами наблюдения. Складывать такие поля в одну
        оценку значило бы сравнивать ряды разной длины.
        """
        statement = select(Field).where(Field.farm_id == farm_id)
        if project_id is not None:
            statement = statement.where(Field.project_id == project_id)
        return list(self._session.scalars(statement.order_by(Field.created_at)).all())

    def add(self, field: Field) -> Field:
        self._session.add(field)
        self._session.flush()
        return field

    def delete(self, field: Field) -> None:
        self._session.delete(field)
