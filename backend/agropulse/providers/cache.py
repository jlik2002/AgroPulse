"""Кэш ответов внешних источников.

Два уровня с разным назначением:

* Redis — быстрый, с истечением срока. Снимает повторные обращения к Earth Engine
  и Open-Meteo при перезапуске анализа того же поля.
* Таблица `raw_cache` в PostgreSQL — долговременный. Переживает перезапуск Redis
  и позволяет воспроизвести результат при недоступном внешнем API. Постановка
  задачи прямо рекомендует иметь такой запас на случай защиты проекта.

Читаем сверху вниз, пишем в оба уровня.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import redis
from sqlalchemy import delete, select

from agropulse.config import get_settings
from agropulse.db.models import RawCache
from agropulse.db.session import session_scope

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 7 * 24 * 3600

_redis_client: redis.Redis | None = None


def _get_redis() -> redis.Redis | None:
    """Клиент Redis. Недоступность кэша не должна ломать пайплайн."""
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = redis.Redis.from_url(
                get_settings().redis_cache_url, decode_responses=True, socket_timeout=2
            )
        except Exception as exc:
            logger.warning("Redis-кэш недоступен: %s", exc)
            return None
    return _redis_client


def make_key(provider: str, **params: Any) -> str:
    """Стабильный ключ кэша по имени провайдера и параметрам запроса.

    Параметры сортируются, поэтому порядок аргументов на ключ не влияет.
    """
    payload = json.dumps(params, sort_keys=True, default=str, ensure_ascii=False)
    digest = hashlib.sha256(payload.encode()).hexdigest()[:32]
    return f"{provider}:{digest}"


def get(key: str) -> Any | None:
    client = _get_redis()
    if client is not None:
        try:
            raw = client.get(key)
            if raw is not None:
                return json.loads(raw)
        except Exception as exc:
            logger.debug("Чтение из Redis не удалось: %s", exc)

    try:
        with session_scope() as db:
            row = db.scalar(select(RawCache).where(RawCache.key == key))
            if row is None:
                return None
            if row.expires_at is not None and row.expires_at < datetime.now(timezone.utc):
                return None
            payload = row.payload
    except Exception as exc:
        logger.debug("Чтение из raw_cache не удалось: %s", exc)
        return None

    # Прогреваем Redis, чтобы следующее чтение не ходило в базу.
    if client is not None:
        try:
            client.setex(key, DEFAULT_TTL_SECONDS, json.dumps(payload, ensure_ascii=False))
        except Exception:
            pass
    return payload


def set(key: str, provider: str, payload: Any, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
    client = _get_redis()
    if client is not None:
        try:
            client.setex(key, ttl_seconds, json.dumps(payload, ensure_ascii=False))
        except Exception as exc:
            logger.debug("Запись в Redis не удалась: %s", exc)

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    try:
        with session_scope() as db:
            # Upsert вручную: строк немного, а зависимость от диалекта здесь лишняя.
            db.execute(delete(RawCache).where(RawCache.key == key))
            db.add(RawCache(key=key, provider=provider, payload=payload, expires_at=expires_at))
    except Exception as exc:
        logger.debug("Запись в raw_cache не удалась: %s", exc)


def cached_call(provider: str, ttl_seconds: int, loader, **params: Any) -> Any:
    """Выполнить запрос через кэш.

    `loader` вызывается только при промахе. Ошибки кэша никогда не всплывают
    наружу: кэш — оптимизация, а не источник истины.
    """
    key = make_key(provider, **params)
    hit = get(key)
    if hit is not None:
        logger.debug("Кэш попал: %s", key)
        return hit

    value = loader()
    set(key, provider, value, ttl_seconds)
    return value
