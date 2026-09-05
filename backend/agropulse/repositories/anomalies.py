"""Хранение аномальных периодов."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from agropulse.db.models import Anomaly

# Порядок вывода: самые тяжёлые события первыми. z-score отрицательный,
# поэтому по возрастанию — значит от самого глубокого отклонения.
_SEVERITY_ORDER = (Anomaly.max_zscore, Anomaly.start_date)


class AnomalyRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_for_field(self, field_id: uuid.UUID) -> list[Anomaly]:
        return list(
            self._session.scalars(
                select(Anomaly).where(Anomaly.field_id == field_id).order_by(*_SEVERITY_ORDER)
            ).all()
        )

    def list_for_fields(self, field_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Anomaly]]:
        """Аномалии нескольких полей одним запросом — см. `ObservationRepository`."""
        if not field_ids:
            return {}

        rows = self._session.scalars(
            select(Anomaly)
            .where(Anomaly.field_id.in_(field_ids))
            .order_by(Anomaly.field_id, *_SEVERITY_ORDER)
        ).all()

        grouped: dict[uuid.UUID, list[Anomaly]] = {field_id: [] for field_id in field_ids}
        for row in rows:
            grouped[row.field_id].append(row)
        return grouped

    def replace_for_field(self, field_id: uuid.UUID, anomalies: list[Anomaly]) -> None:
        """Заместить события поля результатом нового прогона.

        Именно замещение, а не дополнение: аномалия — это вывод из текущего
        состояния ряда, и после пересчёта прежние выводы недействительны.
        """
        self._session.execute(delete(Anomaly).where(Anomaly.field_id == field_id))
        for anomaly in anomalies:
            self._session.add(anomaly)
