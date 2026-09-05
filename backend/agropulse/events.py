"""Шина событий прогресса поверх Redis pub/sub.

Канал выбран вместо памяти процесса намеренно: реплик API может быть
несколько, событие публикует воркер, а SSE-поток держит произвольная реплика.
Через память процесса они бы не встретились.

Источником истины шина не является — им остаётся таблица `jobs`. Поэтому
отказ публикации не прерывает обработку: потерянное событие означает лишь,
что интерфейс узнает о продвижении на секунду позже, при следующем событии
или при переподключении.

Имя канала не менялось при рефакторинге: на него подписаны уже открытые
SSE-соединения.
"""

from __future__ import annotations

import json
import logging
import uuid

import redis

from agropulse.redis_client import get_redis

logger = logging.getLogger(__name__)

CHANNEL_PREFIX = "agropulse:progress"


def progress_channel(project_id: uuid.UUID | str) -> str:
    return f"{CHANNEL_PREFIX}:{project_id}"


def publish_progress(project_id: uuid.UUID | str, event: dict) -> None:
    """Отправить событие подписчикам. Ошибка публикации не прерывает обработку."""
    client = get_redis()
    if client is None:
        return
    try:
        client.publish(
            progress_channel(project_id),
            json.dumps(event, ensure_ascii=False, default=str),
        )
    except (redis.RedisError, TypeError) as exc:
        logger.debug(
            "progress_publish_failed",
            extra={"project_id": str(project_id), "error": str(exc)},
        )
