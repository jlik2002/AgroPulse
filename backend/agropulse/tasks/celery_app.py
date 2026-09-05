"""Настройка Celery.

Две очереди с разным характером нагрузки:

* `collect`  — обращения к GEE, STAC, Open-Meteo. Долгие (минуты), упираются в сеть.
* `analyze`  — климатология, аномалии, риск, отчёты. Быстрые, упираются в CPU.

Разделение нужно не для красоты: в Kubernetes это два отдельных Deployment'а,
которые масштабируются независимо, и медленный сбор данных не блокирует
пересчёт аналитики.

Имена задач и очередей — внешний контракт. В брокере могут лежать сообщения,
опубликованные предыдущей версией сервиса, поэтому переименование задачи
при переносе кода в другой модуль недопустимо.
"""

from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown

from agropulse.config import get_settings
from agropulse.observability import configure_logging

settings = get_settings()

celery_app = Celery(
    "agropulse",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["agropulse.tasks.pipeline"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Подтверждение задачи после выполнения, а не до. Если под убьют посреди
    # обращения к GEE, задача вернётся в очередь и выполнится заново.
    # Обратная сторона — задачи обязаны быть идемпотентными: наблюдения
    # пишутся upsert'ом по (field_id, date, value_type, source).
    task_acks_late=True,
    # Воркер стартует раньше, чем поднимется брокер: в compose это гонка
    # порядка запуска, в кластере — обычное дело при перезапуске узла.
    broker_connection_retry_on_startup=True,
    # Один воркер держит одну задачу. Иначе при рестарте пода теряются
    # разобранные, но не начатые задачи из локального буфера.
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    # Общая верхняя граница. У каждой задачи есть собственные пределы,
    # заданные по её характеру нагрузки; эти значения — страховка на случай
    # задачи, для которой предел забыли указать.
    task_soft_time_limit=settings.collect_soft_time_limit_seconds,
    task_time_limit=settings.collect_time_limit_seconds,
    result_expires=86400,
    task_default_queue="analyze",
    task_routes={
        "agropulse.tasks.pipeline.collect_field_data": {"queue": "collect"},
        "agropulse.tasks.pipeline.analyze_field": {"queue": "analyze"},
        # Полный цикл начинается со сбора, поэтому идёт в сетевую очередь.
        "agropulse.tasks.pipeline.process_field": {"queue": "collect"},
    },
)


@worker_process_init.connect
def setup_worker_process(**_: object) -> None:
    """Настроить процесс воркера.

    Celery поднимает воркеры через fork, поэтому логирование настраивается
    в дочернем процессе, а не на импорте модуля: настройки, применённые
    до fork, наследуются вместе с открытыми дескрипторами родителя.
    """
    configure_logging(settings.log_level, settings.log_json)


@worker_process_shutdown.connect
def teardown_worker_process(**_: object) -> None:
    """Закрыть соединения, чтобы не оставлять их висеть на стороне серверов."""
    from agropulse.db.session import dispose_engine
    from agropulse.redis_client import reset_redis

    dispose_engine()
    reset_redis()
