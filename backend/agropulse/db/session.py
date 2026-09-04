"""Подключение к базе данных.

Движок синхронный и один на оба процесса — api и Celery-воркер. Асинхронный
SQLAlchemy здесь дал бы два разных движка и две ветки кода, потому что воркер
Celery синхронный по своей природе. Обработчики FastAPI объявляются как `def`
и выполняются в пуле потоков; асинхронным остаётся только SSE-эндпоинт,
которому база вообще не нужна.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from agropulse.config import get_settings

_settings = get_settings()

engine = create_engine(
    _settings.database_url,
    pool_pre_ping=True,   # соединение могло протухнуть, пока задача ждала в очереди
    pool_size=5,
    max_overflow=10,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """Зависимость FastAPI: сессия на время запроса."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Сессия для кода вне FastAPI — прежде всего для задач Celery."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
