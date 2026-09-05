"""Единственный клиент Redis для кэша и шины прогресса.

До рефакторинга клиент создавался в двух модулях одинаковым кодом с двумя
глобальными переменными. Это не только дублирование: два пула соединений на
процесс расходуются вдвое быстрее, а починить таймаут приходилось в двух местах.

Брокер Celery сюда не входит. Он живёт в отдельной логической базе и
управляется самим Celery: у очереди и у кэша разные требования к вытеснению,
и терять сообщения из-за переполнения кэша недопустимо.

Недоступность Redis не является ошибкой для вызывающего кода: кэш —
оптимизация, шина прогресса — информирование. Поэтому функция возвращает
`None`, а не возбуждает исключение.
"""

from __future__ import annotations

import logging
import os

import redis

from agropulse.config import get_settings

logger = logging.getLogger(__name__)

_client: redis.Redis | None = None
_client_pid: int | None = None


def get_redis() -> redis.Redis | None:
    """Клиент Redis процесса или `None`, если подключиться не удалось.

    Сверка с PID обязательна: Celery поднимает воркеры через fork, и дочерний
    процесс унаследовал бы сокеты родителя. Два процесса, читающих из одного
    сокета, получают чужие ответы — ошибка, которая проявляется редко и
    выглядит как порча данных.
    """
    global _client, _client_pid

    current_pid = os.getpid()
    if _client is not None and _client_pid == current_pid:
        return _client

    settings = get_settings()
    try:
        _client = redis.Redis.from_url(
            settings.redis_cache_url,
            decode_responses=True,
            socket_timeout=settings.redis_socket_timeout_seconds,
            socket_connect_timeout=settings.redis_socket_timeout_seconds,
        )
    except (redis.RedisError, ValueError) as exc:
        logger.warning("redis_unavailable", extra={"error": str(exc)})
        _client = None
    _client_pid = current_pid
    return _client


def reset_redis() -> None:
    """Закрыть клиент. Нужно при завершении процесса и в тестах."""
    global _client, _client_pid
    if _client is not None:
        _client.close()
    _client = None
    _client_pid = None
