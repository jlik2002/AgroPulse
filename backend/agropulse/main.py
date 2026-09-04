"""Точка входа веб-сервиса AgroPulse."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agropulse.api.routers import analysis, events, fields, health, parcels, projects
from agropulse.config import get_settings
from agropulse.storage import s3

settings = get_settings()
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Бакет создаём здесь, а не миграцией: MinIO может подняться позже базы.
    # Отказ хранилища на старте не должен ронять процесс — это покажет /health/ready.
    try:
        s3.ensure_bucket()
    except Exception as exc:
        logger.warning("Не удалось подготовить бакет на старте: %s", exc)
    yield


app = FastAPI(
    title="AgroPulse",
    description="Сервис дистанционного мониторинга сельскохозяйственных полей",
    version="0.1.0",
    lifespan=lifespan,
)

# В разработке фронтенд поднимается отдельным origin (Vite на 5173).
# В кластере api и web стоят за одним Ingress, и CORS не задействован.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.app_env == "local" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Пробы живут вне префикса /api: их дёргает инфраструктура, а не клиент.
app.include_router(health.router)

app.include_router(projects.router, prefix=settings.api_prefix)
app.include_router(fields.router, prefix=settings.api_prefix)
app.include_router(parcels.router, prefix=settings.api_prefix)
app.include_router(analysis.router, prefix=settings.api_prefix)
app.include_router(events.router, prefix=settings.api_prefix)
