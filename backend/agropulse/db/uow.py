"""Единица работы: сессия, репозитории и граница транзакции.

Смысл в одном: у бизнес-операции должна быть ровно одна граница транзакции.
До рефакторинга `commit` вызывался из роутеров и из служебных функций, поэтому
«обновить контур поля» состояло из нескольких независимых транзакций, и падение
посередине оставляло поле с новой геометрией, но старыми наблюдениями.

Решение о `commit` принимает сервис. Репозитории только читают и пишут.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from types import TracebackType

from sqlalchemy.orm import Session

from agropulse.db.session import create_session
from agropulse.repositories import (
    AnomalyRepository,
    FieldRepository,
    ForecastRepository,
    JobRepository,
    ObservationRepository,
    ProjectRepository,
    RawCacheRepository,
)


class UnitOfWork:
    """Репозитории поверх одной сессии.

    Объект оборачивает уже существующую сессию: в HTTP-запросе её создаёт
    зависимость FastAPI, в задаче Celery — `unit_of_work()`. Собственную
    сессию класс не заводит, чтобы не было двух источников соединений.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.projects = ProjectRepository(session)
        self.fields = FieldRepository(session)
        self.observations = ObservationRepository(session)
        self.anomalies = AnomalyRepository(session)
        self.forecasts = ForecastRepository(session)
        self.jobs = JobRepository(session)
        self.raw_cache = RawCacheRepository(session)

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()

    def flush(self) -> None:
        self.session.flush()

    def __enter__(self) -> UnitOfWork:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        # Незавершённая транзакция откатывается всегда: выход из блока без
        # явного commit означает, что операция не была доведена до конца.
        if exc_type is not None:
            self.rollback()
        return False


@contextmanager
def unit_of_work() -> Iterator[UnitOfWork]:
    """Единица работы с собственной сессией — для Celery и CLI.

    Успешный выход из блока фиксирует транзакцию, исключение откатывает.
    Сессия закрывается в любом случае: держать её открытой между задачами
    нельзя, соединение вернётся в пул протухшим.
    """
    session = create_session()
    uow = UnitOfWork(session)
    try:
        yield uow
        uow.commit()
    except Exception:
        uow.rollback()
        raise
    finally:
        session.close()
