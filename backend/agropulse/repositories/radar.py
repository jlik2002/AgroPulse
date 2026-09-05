"""Хранение радарного ряда поля.

Пишется upsert'ом по тем же соображениям, что и оптические наблюдения: задача
сбора может выполниться повторно после рестарта воркера, и повтор обязан
обновить строку, а не создать дубль.

Производные величины (разности, резкость перехода) обновляются отдельно, уже
на стадии анализа. Разделение не формальное: измеренные значения зависят
только от снимка, производные — от всего ряда целиком, и пересчитывать их
нужно каждый раз, когда ряд пополнился.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from agropulse.db.models import RadarObservation

# Что повторный сбор обязан обновить. Ключ идентичности
# (field_id, date, source) в набор не входит.
_UPDATABLE_COLUMNS = (
    "orbit_direction",
    "relative_orbit",
    "vv_median_db",
    "vh_median_db",
    "vh_vv_difference_db",
    "rvi_median",
    "spatial_iqr_db",
    "low_signal_fraction",
    "valid_fraction",
    "scene_id",
    "missing_reason",
)


class RadarObservationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_for_field(self, field_id: uuid.UUID) -> list[RadarObservation]:
        statement = (
            select(RadarObservation)
            .where(RadarObservation.field_id == field_id)
            .order_by(RadarObservation.date)
        )
        return list(self._session.scalars(statement).all())

    def list_for_fields(
        self, field_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[RadarObservation]]:
        """Ряды нескольких полей одним запросом — как и для оптики."""
        if not field_ids:
            return {}

        rows = self._session.scalars(
            select(RadarObservation)
            .where(RadarObservation.field_id.in_(field_ids))
            .order_by(RadarObservation.field_id, RadarObservation.date)
        ).all()

        grouped: dict[uuid.UUID, list[RadarObservation]] = {
            field_id: [] for field_id in field_ids
        }
        for row in rows:
            grouped[row.field_id].append(row)
        return grouped

    def upsert(self, rows: list[dict]) -> int:
        if not rows:
            return 0

        statement = pg_insert(RadarObservation).values(rows)
        statement = statement.on_conflict_do_update(
            constraint="uq_radar_observation_identity",
            set_={column: statement.excluded[column] for column in _UPDATABLE_COLUMNS},
        )
        self._session.execute(statement)
        return len(rows)

    def set_derived(self, field_id: uuid.UUID, values: dict[object, dict]) -> None:
        """Проставить производные величины по датам.

        Даты, для которых производную посчитать не удалось (первый снимок
        орбиты, разрыв в ряду), обнуляются: прежнее значение относилось бы
        к прошлому составу ряда.
        """
        rows = self._session.execute(
            select(RadarObservation.id, RadarObservation.date).where(
                RadarObservation.field_id == field_id
            )
        ).all()
        if not rows:
            return

        payload = [
            {
                "id": row.id,
                "vv_change_db": values.get(row.date, {}).get("vv_change_db"),
                "vh_change_db": values.get(row.date, {}).get("vh_change_db"),
                "rvi_change": values.get(row.date, {}).get("rvi_change"),
                "change_point_score": values.get(row.date, {}).get("change_point_score"),
            }
            for row in rows
        ]
        self._session.execute(update(RadarObservation), payload)

    def delete_for_field(self, field_id: uuid.UUID) -> None:
        self._session.execute(
            delete(RadarObservation).where(RadarObservation.field_id == field_id)
        )
