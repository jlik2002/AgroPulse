"""Публикация фоновых задач.

Сервисный слой не должен знать про Celery: «поставить обработку поля в очередь» —
это бизнес-намерение, а брокер и имя задачи — деталь реализации. Отдельный
объект даёт две вещи: сервис остаётся проверяемым без брокера, а переход
на другой транспорт затрагивает только этот модуль.

В задачу уходит один идентификатор, а не объект поля. Воркер сам читает
актуальные данные из PostgreSQL: сериализованный ORM-объект в очереди
устаревает к моменту выполнения и ломается при любом изменении схемы.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from agropulse.tasks.pipeline import process_field


class TaskPublisher(Protocol):
    """Контракт публикации задач, известный сервисному слою."""

    def publish_field_processing(self, field_id: uuid.UUID) -> str:
        """Поставить полный цикл обработки поля. Возвращает идентификатор задачи."""
        ...


class CeleryTaskPublisher:
    def publish_field_processing(self, field_id: uuid.UUID) -> str:
        return process_field.delay(str(field_id)).id
