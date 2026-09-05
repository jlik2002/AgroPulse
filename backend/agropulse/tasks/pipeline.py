"""Celery-задачи пайплайна: тонкие адаптеры над `services/pipeline.py`.

Задача не содержит бизнес-логики. Её работа — разобрать аргументы, задать
политику повторов и пределы времени, обеспечить конечный статус при неудаче
и передать управление сервису. Благодаря этому ту же обработку можно
выполнить из теста или CLI, не поднимая брокер.

Имена задач и очереди менять нельзя: в брокере могут лежать сообщения,
опубликованные предыдущей версией сервиса.

Повтор выполняется только для `TransientPipelineError`. Повторять всё подряд
означало бы повторять ошибки программирования и некорректные данные: воркеры
заняты, диагностика отложена, результат тот же.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Any

from celery import Task
from celery.exceptions import SoftTimeLimitExceeded

from agropulse.config import get_settings
from agropulse.errors import PipelineError, TransientPipelineError
from agropulse.observability import task_context
from agropulse.services.pipeline import FieldMissing, FieldPipeline
from agropulse.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

_settings = get_settings()

# Общая политика повторов. Экспоненциальная задержка с разбросом: без разброса
# все задачи, упавшие из-за одного отказа GEE, вернутся одновременно и повторят
# его же.
_RETRY_POLICY: dict[str, Any] = {
    "autoretry_for": (TransientPipelineError,),
    "retry_backoff": True,
    "retry_jitter": True,
    "max_retries": _settings.task_max_retries,
}

_TIMEOUT_ERROR_CODE = "task_timeout"


def _execute(
    task: Task,
    field_id: str,
    operation: Callable[[FieldPipeline, uuid.UUID], dict],
    error_code: str,
) -> dict:
    """Выполнить операцию пайплайна с гарантией конечного состояния.

    Единственное место, где решается судьба неудачной обработки. Правила:

    * поля больше нет — задача завершается штатно, повторять нечего;
    * временная ошибка — повтор, а на последней попытке поле помечается
      неудачей: иначе оно навсегда осталось бы в ожидании;
    * превышение мягкого лимита времени и любая другая ошибка — конечный
      статус сразу, без повтора.
    """
    settings = get_settings()
    field_uuid = uuid.UUID(field_id)
    task_id = task.request.id
    # Номер попытки попадает во все записи задачи: по нему видно, сколько
    # повторов реально происходит, и стоит ли за ними системная проблема.
    attempt = task.request.retries

    with task_context(task_id):
        pipeline = FieldPipeline(settings, task_id=task_id)
        try:
            result = operation(pipeline, field_uuid)
            if attempt:
                logger.info(
                    "pipeline_recovered_after_retry",
                    extra={"field_id": field_id, "attempt": attempt},
                )
            return result
        except FieldMissing:
            logger.warning("field_missing_task_skipped", extra={"field_id": field_id})
            return {"field_id": field_id, "status": "not_found"}
        except TransientPipelineError as exc:
            if attempt >= task.max_retries:
                logger.error(
                    "pipeline_retries_exhausted",
                    extra={"field_id": field_id, "error_code": exc.code, "attempt": attempt},
                )
                pipeline.mark_failed(field_uuid, exc.code)
            else:
                logger.warning(
                    "pipeline_transient_failure",
                    extra={"field_id": field_id, "error_code": exc.code, "attempt": attempt},
                )
            raise
        except SoftTimeLimitExceeded:
            logger.error("pipeline_timeout", extra={"field_id": field_id, "attempt": attempt})
            pipeline.mark_failed(field_uuid, _TIMEOUT_ERROR_CODE)
            raise
        except Exception as exc:
            code = exc.code if isinstance(exc, PipelineError) else error_code
            logger.exception(
                "pipeline_failed",
                extra={"field_id": field_id, "error_code": code, "attempt": attempt},
            )
            pipeline.mark_failed(field_uuid, code)
            raise


@celery_app.task(
    name="agropulse.tasks.pipeline.collect_field_data",
    bind=True,
    soft_time_limit=_settings.collect_soft_time_limit_seconds,
    time_limit=_settings.collect_time_limit_seconds,
    **_RETRY_POLICY,
)
def collect_field_data(self: Task, field_id: str) -> dict:
    """Собрать спутниковые наблюдения и погоду по одному полю."""
    return _execute(self, field_id, lambda p, fid: p.collect(fid), "collect_failed")


@celery_app.task(
    name="agropulse.tasks.pipeline.analyze_field",
    bind=True,
    soft_time_limit=_settings.analyze_soft_time_limit_seconds,
    time_limit=_settings.analyze_time_limit_seconds,
    **_RETRY_POLICY,
)
def analyze_field(self: Task, field_id: str) -> dict:
    """Восстановить пропуски, найти аномалии, оценить риск и прогноз."""
    return _execute(self, field_id, lambda p, fid: p.analyze(fid), "analyze_failed")


@celery_app.task(
    name="agropulse.tasks.pipeline.process_field",
    bind=True,
    soft_time_limit=(
        _settings.collect_soft_time_limit_seconds + _settings.analyze_soft_time_limit_seconds
    ),
    time_limit=(
        _settings.collect_time_limit_seconds + _settings.analyze_time_limit_seconds
    ),
    **_RETRY_POLICY,
)
def process_field(self: Task, field_id: str) -> dict:
    """Полный цикл по полю: сбор и следом анализ.

    Отдельная задача-обёртка нужна, чтобы интерфейс запускал обработку одним
    вызовом, а не выстраивал цепочку сам. Повтор возвращает к началу цикла:
    сбор идемпотентен, поэтому повторный проход не портит уже собранное.
    """
    return _execute(self, field_id, _collect_then_analyze, "process_failed")


def _collect_then_analyze(pipeline: FieldPipeline, field_id: uuid.UUID) -> dict:
    collected = pipeline.collect(field_id)
    analyzed = pipeline.analyze(field_id)
    return {**collected, **analyzed}
