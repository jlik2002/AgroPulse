"""Долговременный кэш ответов внешних источников.

Второй уровень кэша после Redis. Переживает перезапуск Redis и позволяет
воспроизвести результат при недоступном внешнем API — на защите проекта это
единственная гарантия, что демонстрация состоится.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from agropulse.db.models import RawCache


class RawCacheRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, key: str) -> Any | None:
        row = self._session.scalar(select(RawCache).where(RawCache.key == key))
        if row is None:
            return None
        if row.expires_at is not None and row.expires_at < datetime.now(UTC):
            return None
        return row.payload

    def set(self, key: str, provider: str, payload: Any, expires_at: datetime) -> None:
        """Записать значение, заместив прежнее.

        Upsert, а не «удалить и вставить»: две задачи могут греть один ключ
        одновременно, и последовательность DELETE + INSERT приводит к гонке
        с нарушением первичного ключа.
        """
        statement = pg_insert(RawCache).values(
            key=key, provider=provider, payload=payload, expires_at=expires_at
        )
        self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[RawCache.key],
                set_={
                    "provider": statement.excluded.provider,
                    "payload": statement.excluded.payload,
                    "expires_at": statement.excluded.expires_at,
                    "fetched_at": datetime.now(UTC),
                },
            )
        )
