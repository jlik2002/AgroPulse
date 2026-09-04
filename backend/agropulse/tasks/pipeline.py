"""Задачи пайплайна обработки поля.

Каркас этапа E0: задачи зарегистрированы в Celery и маршрутизируются по своим
очередям, но содержательная часть появляется на следующих этапах —
сбор данных из GEE на E1, аналитика на E4.

Обе задачи обязаны быть идемпотентными: при `task_acks_late` рестарт воркера
возвращает задачу в очередь, и повторный прогон не должен плодить дубли.
"""

import logging

from agropulse.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="agropulse.tasks.pipeline.collect_field_data", bind=True)
def collect_field_data(self, field_id: str) -> dict[str, str]:
    """Сбор спутниковых и погодных данных по одному полю.

    Очередь `collect`: задача упирается в сеть и длится минуты.
    """
    logger.info("Сбор данных по полю %s (заглушка этапа E0)", field_id)
    return {"field_id": field_id, "status": "not_implemented"}


@celery_app.task(name="agropulse.tasks.pipeline.analyze_field", bind=True)
def analyze_field(self, field_id: str) -> dict[str, str]:
    """Климатология, аномалии, составной риск и прогноз по одному полю.

    Очередь `analyze`: задача упирается в CPU и считается быстро.
    """
    logger.info("Анализ поля %s (заглушка этапа E0)", field_id)
    return {"field_id": field_id, "status": "not_implemented"}
