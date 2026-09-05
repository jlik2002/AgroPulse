"""Хранение временного ряда поля.

Наблюдения, восстановленные значения и прогноз лежат в одной таблице и
различаются полем `value_type`. Это сделано ради чтения: график и выгрузка CSV
собираются одним запросом, а не склейкой трёх источников.

Записываются они по-разному, и разница принципиальна:

* наблюдения пишутся upsert'ом — задача сбора может выполниться повторно
  после рестарта воркера, и повтор обязан обновить строку, а не создать дубль;
* восстановленные значения и прогноз замещаются целиком — изменившийся набор
  наблюдений делает часть прежних расчётов недействительной, и upsert оставил
  бы их в ряду.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from agropulse.db.models import Observation, ValueType

# Поля, которые повторный сбор обязан обновить. Ключ идентичности
# (field_id, date, value_type, source) в набор не входит.
_OBSERVED_UPDATABLE_COLUMNS = (
    "ndvi_mean",
    "ndmi_mean",
    "evi_mean",
    "valid_fraction",
    "cloud_fraction",
    "scene_id",
    "missing_reason",
    "temperature",
    "precipitation",
)


class ObservationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Чтение
    # ------------------------------------------------------------------

    def list_for_field(
        self, field_id: uuid.UUID, value_types: tuple[ValueType, ...] | None = None
    ) -> list[Observation]:
        statement = select(Observation).where(Observation.field_id == field_id)
        if value_types is not None:
            statement = statement.where(Observation.value_type.in_(value_types))
        statement = statement.order_by(Observation.date, Observation.value_type)
        return list(self._session.scalars(statement).all())

    def list_for_fields(
        self, field_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[Observation]]:
        """Ряды нескольких полей одним запросом.

        Сводка проекта и сводный отчёт читают все поля сразу. Запрос на поле
        в цикле — тот самый N+1, который на хозяйстве в сотню полей превращает
        открытие дашборда в сотни обращений к базе.
        """
        if not field_ids:
            return {}

        rows = self._session.scalars(
            select(Observation)
            .where(Observation.field_id.in_(field_ids))
            .order_by(Observation.field_id, Observation.date, Observation.value_type)
        ).all()

        grouped: dict[uuid.UUID, list[Observation]] = {field_id: [] for field_id in field_ids}
        for row in rows:
            grouped[row.field_id].append(row)
        return grouped

    # ------------------------------------------------------------------
    # Запись
    # ------------------------------------------------------------------

    def upsert_observed(self, rows: list[dict]) -> int:
        """Записать наблюдения, обновив уже существующие даты."""
        if not rows:
            return 0

        statement = pg_insert(Observation).values(rows)
        statement = statement.on_conflict_do_update(
            constraint="uq_observation_identity",
            set_={column: statement.excluded[column] for column in _OBSERVED_UPDATABLE_COLUMNS},
        )
        self._session.execute(statement)
        return len(rows)

    def replace_restored(self, field_id: uuid.UUID, rows: list[dict]) -> None:
        self._replace(field_id, ValueType.RESTORED, rows)

    def replace_forecast(self, field_id: uuid.UUID, rows: list[dict]) -> None:
        self._replace(field_id, ValueType.FORECAST, rows)

    def _replace(self, field_id: uuid.UUID, value_type: ValueType, rows: list[dict]) -> None:
        self._session.execute(
            delete(Observation).where(
                Observation.field_id == field_id,
                Observation.value_type == value_type,
            )
        )
        if rows:
            self._session.execute(pg_insert(Observation).values(rows))

    def delete_for_field(self, field_id: uuid.UUID) -> None:
        self._session.execute(delete(Observation).where(Observation.field_id == field_id))

    def set_climatology(
        self,
        field_id: uuid.UUID,
        zscores: dict[date, float],
        bands: dict[date, tuple[float, float]],
    ) -> None:
        """Проставить отклонение от нормы и сам коридор нормы по датам.

        Даты, для которых норма не построена, обнуляются: прежнее значение
        относилось бы к предыдущей норме и вводило бы в заблуждение.

        Прогнозные строки обновляются только по z-score: их `ndvi_lo`/`ndvi_hi` —
        это доверительный интервал предсказания, а не коридор нормы, и затирать
        его климатологией нельзя.

        Обновление уходит пакетами по первичным ключам, а не запросом на дату:
        ряд поля за несколько сезонов — это сотни строк.
        """
        rows = self._session.execute(
            select(Observation.id, Observation.date, Observation.value_type).where(
                Observation.field_id == field_id
            )
        ).all()
        if not rows:
            return

        historical: list[dict] = []
        forecast: list[dict] = []
        for row in rows:
            if row.value_type == ValueType.FORECAST:
                forecast.append({"id": row.id, "ndvi_zscore": zscores.get(row.date)})
                continue
            band = bands.get(row.date)
            historical.append(
                {
                    "id": row.id,
                    "ndvi_zscore": zscores.get(row.date),
                    "ndvi_lo": band[0] if band else None,
                    "ndvi_hi": band[1] if band else None,
                }
            )

        # Два вызова, а не один: у наборов разный состав колонок, и общий
        # bulk-update пришлось бы кормить лишними полями прогнозных строк.
        if historical:
            self._session.execute(update(Observation), historical)
        if forecast:
            self._session.execute(update(Observation), forecast)
