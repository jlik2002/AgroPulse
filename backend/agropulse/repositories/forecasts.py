"""Хранение метаданных прогноза. Сами точки лежат в `observations`."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from agropulse.db.models import ForecastRun


class ForecastRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_field(self, field_id: uuid.UUID) -> ForecastRun | None:
        return self._session.scalar(
            select(ForecastRun).where(ForecastRun.field_id == field_id)
        )

    def get_for_fields(self, field_ids: list[uuid.UUID]) -> dict[uuid.UUID, ForecastRun]:
        if not field_ids:
            return {}
        rows = self._session.scalars(
            select(ForecastRun).where(ForecastRun.field_id.in_(field_ids))
        ).all()
        return {row.field_id: row for row in rows}

    def delete_for_field(self, field_id: uuid.UUID) -> None:
        self._session.execute(delete(ForecastRun).where(ForecastRun.field_id == field_id))

    def replace_for_field(self, field_id: uuid.UUID, run: ForecastRun) -> None:
        """Оставить один актуальный прогон на поле.

        Уникальность закреплена ограничением `uq_forecast_run_field`: только
        Python-проверки здесь мало, два параллельных пересчёта одного поля
        иначе оставили бы две строки, и чтение выбрало бы произвольную.
        """
        self._session.execute(delete(ForecastRun).where(ForecastRun.field_id == field_id))
        self._session.add(run)
