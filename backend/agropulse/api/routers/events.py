"""Поток прогресса обработки через Server-Sent Events.

SSE, а не WebSocket: поток односторонний, переподключение браузер делает сам,
и он проходит через обычный HTTP-прокси без отдельной настройки апгрейда.

Единственный асинхронный эндпоинт сервиса. Остальные объявлены как `def` и
выполняются в пуле потоков вместе с синхронным SQLAlchemy; здесь же база
не нужна вовсе — только подписка на Redis.
"""

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from redis import asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from agropulse.config import get_settings
from agropulse.db.models import Job, Project
from agropulse.db.session import get_db
from agropulse.tasks.progress import STAGE_ORDER, STAGE_TITLES, channel

logger = logging.getLogger(__name__)
router = APIRouter(tags=["events"])

# Интервал контрольных сообщений. Без них прокси и балансировщики закрывают
# простаивающее соединение по таймауту.
HEARTBEAT_SECONDS = 15


@router.get("/projects/{project_id}/events")
async def project_events(
    project_id: uuid.UUID, request: Request, db: Session = Depends(get_db)
) -> EventSourceResponse:
    """Поток событий обработки проекта.

    Первым сообщением уходит текущее состояние всех стадий: клиент,
    подключившийся к середине обработки, сразу видит полную картину,
    а не ждёт следующего события.
    """
    if db.get(Project, project_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="проект не найден")

    snapshot = _build_snapshot(db, project_id)
    settings = get_settings()

    async def event_stream():
        yield {"event": "snapshot", "data": json.dumps(snapshot, ensure_ascii=False)}

        client = aioredis.from_url(settings.redis_cache_url, decode_responses=True)
        pubsub = client.pubsub()
        await pubsub.subscribe(channel(project_id))
        try:
            while True:
                if await request.is_disconnected():
                    break
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=HEARTBEAT_SECONDS
                )
                if message is None:
                    # Держим соединение живым, пока обработка идёт молча.
                    yield {"event": "ping", "data": "{}"}
                    continue
                yield {"event": "progress", "data": message["data"]}
        except asyncio.CancelledError:
            raise
        finally:
            await pubsub.unsubscribe(channel(project_id))
            await pubsub.aclose()
            await client.aclose()

    return EventSourceResponse(event_stream())


def _build_snapshot(db: Session, project_id: uuid.UUID) -> dict:
    """Текущее состояние стадий по всем полям проекта."""
    jobs = db.scalars(select(Job).where(Job.project_id == project_id)).all()

    by_field: dict[str, list[dict]] = {}
    for job in jobs:
        by_field.setdefault(str(job.field_id), []).append(
            {
                "stage": job.stage.value,
                "stage_title": STAGE_TITLES[job.stage],
                "stage_index": STAGE_ORDER.index(job.stage) + 1,
                "status": job.status.value,
                "progress": job.progress,
                "message": job.message,
                "error": job.error,
            }
        )

    for stages in by_field.values():
        stages.sort(key=lambda item: item["stage_index"])

    return {
        "project_id": str(project_id),
        "stage_total": len(STAGE_ORDER),
        "stages": [
            {"stage": stage.value, "title": STAGE_TITLES[stage], "index": index + 1}
            for index, stage in enumerate(STAGE_ORDER)
        ],
        "fields": by_field,
    }
