"""Подключение к базе данных.

Движок синхронный и один на оба процесса — api и Celery-воркер. Асинхронный
SQLAlchemy здесь дал бы два разных движка и две ветки кода, потому что воркер
Celery синхронный по своей природе. Обработчики FastAPI объявляются как `def`
и выполняются в пуле потоков; асинхронным остаётся только SSE-эндпоинт,
которому база вообще не нужна.

Движок создаётся лениво, а не на импорте модуля: импорт не должен открывать
соединения. Иначе любой запуск, где базы ещё нет — сборка образа, прогон
модульных тестов, вызов `--help` у CLI, — упирался бы в PostgreSQL.

Сессия живёт ровно столько, сколько длится одна операция: HTTP-запрос или
Celery-задача. Глобальной сессии в сервисе нет.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from agropulse.config import get_settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Движок процесса. Создаётся при первом обращении."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            # Соединение могло протухнуть, пока задача ждала в очереди.
            pool_pre_ping=True,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            future=True,
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(), autoflush=False, expire_on_commit=False
        )
    return _session_factory


def create_session() -> Session:
    """Новая сессия. Закрыть её обязан вызывающий."""
    return get_session_factory()()


def dispose_engine() -> None:
    """Закрыть пул соединений.

    Нужно при завершении процесса и в тестах, где база удаляется:
    открытые соединения не дадут выполнить DROP DATABASE.
    """
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def get_db() -> Iterator[Session]:
    """Зависимость FastAPI: сессия на время запроса.

    Транзакцией управляет вызванный сервис, а не эта зависимость: границей
    транзакции является бизнес-операция, а не HTTP-запрос.
    """
    session = create_session()
    try:
        yield session
    finally:
        session.close()
