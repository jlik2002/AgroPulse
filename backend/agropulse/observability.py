"""Логи и сквозные идентификаторы.

Задача модуля одна: по логам должно быть можно восстановить, что происходило
с конкретным запросом или конкретной задачей, не меняя код ради диагностики.

Для этого в каждую запись подмешиваются `request_id` (HTTP) и `task_id`
(Celery). Идентификаторы живут в `contextvars`, поэтому их не нужно протаскивать
аргументом через все слои, и они не путаются между запросами в пуле потоков:
контекст копируется при переходе в поток, а не разделяется.
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_task_id: ContextVar[str | None] = ContextVar("task_id", default=None)

# Поля, которые LogRecord несёт всегда. Всё, чего здесь нет, считается
# добавленным через `extra` и уходит в структурированный вывод.
_STANDARD_RECORD_FIELDS = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__
) | {"message", "asctime", "taskName"}


def new_request_id() -> str:
    return uuid.uuid4().hex


def get_request_id() -> str | None:
    return _request_id.get()


def get_task_id() -> str | None:
    return _task_id.get()


@contextmanager
def request_context(request_id: str) -> Iterator[str]:
    token = _request_id.set(request_id)
    try:
        yield request_id
    finally:
        _request_id.reset(token)


@contextmanager
def task_context(task_id: str | None) -> Iterator[str | None]:
    token = _task_id.set(task_id)
    try:
        yield task_id
    finally:
        _task_id.reset(token)


class CorrelationFilter(logging.Filter):
    """Подмешивает сквозные идентификаторы в каждую запись."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get() or "-"
        record.task_id = _task_id.get() or "-"
        return True


class JsonFormatter(logging.Formatter):
    """Однострочный JSON — формат, который читает сборщик логов в кластере."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "task_id": getattr(record, "task_id", "-"),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_FIELDS and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO", json_output: bool = False) -> None:
    """Настроить корневой логгер.

    Вызывается один раз при сборке приложения или старте воркера, а не на
    импорте модуля: импорт не должен менять глобальное состояние процесса.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(CorrelationFilter())
    handler.setFormatter(
        JsonFormatter()
        if json_output
        else logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s [req=%(request_id)s task=%(task_id)s]: %(message)s"
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
