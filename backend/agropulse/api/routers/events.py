"""Поток прогресса обработки через Server-Sent Events.

SSE, а не WebSocket: поток односторонний, переподключение браузер делает сам,
и он проходит через обычный HTTP-прокси без отдельной настройки апгрейда.

Единственный асинхронный эндпоинт сервиса. Остальные объявлены как `def` и
выполняются в пуле потоков вместе с синхронным SQLAlchemy; здесь же база
нужна только для первого сообщения — дальше идёт подписка на Redis.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from redis import asyncio as aioredis
from sse_starlette.sse import EventSourceResponse

from agropulse.api.deps import SettingsDep, UnitOfWorkDep
from agropulse.errors import ProjectNotFoundError
from agropulse.events import progress_channel
from agropulse.services.progress import build_snapshot

logger = logging.getLogger(__name__)
router = APIRouter(tags=["events"])

# Интервал контрольных сообщений. Без них прокси и балансировщики закрывают
# простаивающее соединение по таймауту.
HEARTBEAT_SECONDS = 15


@router.get("/projects/{project_id}/events")
async def project_events(
    project_id: uuid.UUID,
    request: Request,
    uow: UnitOfWorkDep,
    settings: SettingsDep,
) -> EventSourceResponse:
    """Поток событий обработки проекта.

    Первым сообщением уходит текущее состояние всех стадий: клиент,
    подключившийся к середине обработки, сразу видит полную картину,
    а не ждёт следующего события.
    """
    if not uow.projects.exists(project_id):
        raise ProjectNotFoundError(project_id=str(project_id))

    snapshot = build_snapshot(uow, project_id)
    channel = progress_channel(project_id)

    async def event_stream() -> AsyncIterator[dict]:
        yield {"event": "snapshot", "data": json.dumps(snapshot, ensure_ascii=False)}

        # Собственный асинхронный клиент на соединение: подписка pub/sub
        # занимает соединение целиком и не может делить его с другими.
        client = aioredis.from_url(settings.redis_cache_url, decode_responses=True)
        pubsub = client.pubsub()
        await pubsub.subscribe(channel)
        try:
            while not await request.is_disconnected():
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
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
            await client.aclose()

    return EventSourceResponse(event_stream())
