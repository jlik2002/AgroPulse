"""Кэш ответов внешних источников.

Два уровня с разным назначением:

* Redis — быстрый, с истечением срока. Снимает повторные обращения к Earth Engine
  и Open-Meteo при перезапуске анализа того же поля.
* Таблица `raw_cache` в PostgreSQL — долговременный. Переживает перезапуск Redis
  и позволяет воспроизвести результат при недоступном внешнем API. Постановка
  задачи прямо рекомендует иметь такой запас на случай защиты проекта.

Читаем сверху вниз, пишем в оба уровня.

Ни одна ошибка кэша не всплывает наружу. Кэш — оптимизация, а не источник
истины: недоступный Redis обязан приводить к повторному запросу к источнику,
а не к отказу в обработке поля.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import redis
from sqlalchemy.exc import SQLAlchemyError

from agropulse.config import get_settings
from agropulse.db.uow import unit_of_work
from agropulse.redis_client import get_redis

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 7 * 24 * 3600


def make_key(provider: str, **params: Any) -> str:
    """Стабильный ключ кэша по имени провайдера и параметрам запроса.

    Параметры сортируются, поэтому порядок аргументов на ключ не влияет.
    Префикс включает окружение и версию формата: стенды, нацеленные на один
    Redis, не читают чужие ответы, а смена формата значения не требует
    ручной чистки — старые ключи просто перестают находиться.
    """
    payload = json.dumps(params, sort_keys=True, default=str, ensure_ascii=False)
    digest = hashlib.sha256(payload.encode()).hexdigest()[:32]
    return f"{get_settings().cache_namespace}:{provider}:{digest}"


def get(key: str) -> Any | None:
    """Прочитать значение: сначала Redis, затем долговременный уровень."""
    client = get_redis()
    if client is not None:
        try:
            raw = client.get(key)
            if raw is not None:
                return json.loads(raw)
        except (redis.RedisError, ValueError) as exc:
            logger.debug("cache_read_failed", extra={"key": key, "error": str(exc)})

    try:
        with unit_of_work() as uow:
            payload = uow.raw_cache.get(key)
    except SQLAlchemyError as exc:
        logger.debug("raw_cache_read_failed", extra={"key": key, "error": str(exc)})
        return None

    if payload is None:
        return None

    # Прогреваем Redis, чтобы следующее чтение не ходило в базу.
    _write_to_redis(key, payload, DEFAULT_TTL_SECONDS)
    return payload


def set(key: str, provider: str, payload: Any, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
    """Записать значение на оба уровня."""
    _write_to_redis(key, payload, ttl_seconds)

    expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    try:
        with unit_of_work() as uow:
            uow.raw_cache.set(key, provider, payload, expires_at)
    except SQLAlchemyError as exc:
        logger.debug("raw_cache_write_failed", extra={"key": key, "error": str(exc)})


def _write_to_redis(key: str, payload: Any, ttl_seconds: int) -> None:
    """Записать в Redis с обязательным сроком жизни.

    TTL задаётся всегда: ключ кэша без срока жизни рано или поздно вытесняет
    из памяти то, что нужнее, и никто не может сказать, когда он появился.
    """
    client = get_redis()
    if client is None:
        return
    try:
        client.setex(key, ttl_seconds, json.dumps(payload, ensure_ascii=False))
    except (redis.RedisError, TypeError) as exc:
        logger.debug("cache_write_failed", extra={"key": key, "error": str(exc)})


def cached_call(
    provider: str, ttl_seconds: int, loader: Callable[[], Any], **params: Any
) -> Any:
    """Выполнить запрос через кэш. `loader` вызывается только при промахе."""
    key = make_key(provider, **params)
    hit = get(key)
    if hit is not None:
        logger.debug("cache_hit", extra={"provider": provider})
        return hit

    value = loader()
    set(key, provider, value, ttl_seconds)
    return value
