"""Точка входа веб-сервиса AgroPulse.

Приложение собирается функцией, а не создаётся на импорте модуля. Это нужно
не ради формы: импорт не должен настраивать логирование всего процесса и
читать конфигурацию. С фабрикой тест поднимает собственный экземпляр с
подменёнными зависимостями, а `uvicorn --factory` получает то же приложение,
что и тест.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agropulse.api.errors import register_exception_handlers
from agropulse.api.middleware import RequestContextMiddleware
from agropulse.api.routers import (
    analysis,
    events,
    fields,
    health,
    parcels,
    projects,
    reports,
)
from agropulse.config import Settings, get_settings
from agropulse.observability import configure_logging
from agropulse.storage import s3

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Бакет создаём здесь, а не миграцией: MinIO может подняться позже базы.
    # Отказ хранилища на старте не должен ронять процесс — это покажет /health/ready.
    try:
        s3.ensure_bucket()
    except Exception as exc:
        logger.warning("bucket_prepare_failed", extra={"error": str(exc)})

    yield

    # Соединения закрываются явно: иначе при остановке пода они остаются
    # висеть на стороне PostgreSQL и Redis до их собственного таймаута.
    from agropulse.db.session import dispose_engine
    from agropulse.redis_client import reset_redis

    dispose_engine()
    reset_redis()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Собрать приложение.

    Настройки читаются один раз здесь и передаются компонентам, а не
    вычитываются каждым модулем самостоятельно.
    """
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    app = FastAPI(
        title="AgroPulse",
        description="Сервис дистанционного мониторинга сельскохозяйственных полей",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Порядок важен: контекст запроса должен существовать к моменту, когда
    # обработчик ошибок соберёт ответ с `request_id`.
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.resolved_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    # Пробы живут вне префикса /api: их дёргает инфраструктура, а не клиент.
    app.include_router(health.router)

    for router in (projects, fields, parcels, analysis, events, reports):
        app.include_router(router.router, prefix=settings.api_prefix)

    return app
