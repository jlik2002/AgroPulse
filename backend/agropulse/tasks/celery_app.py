"""Настройка Celery.

Две очереди с разным характером нагрузки:

* `collect`  — обращения к GEE, STAC, Open-Meteo. Долгие (минуты), упираются в сеть.
* `analyze`  — климатология, аномалии, риск, отчёты. Быстрые, упираются в CPU.

Разделение нужно не для красоты: в Kubernetes это два отдельных Deployment'а,
которые масштабируются независимо, и медленный сбор данных не блокирует
пересчёт аналитики.
"""

from celery import Celery

from agropulse.config import get_settings

settings = get_settings()

celery_app = Celery(
    "agropulse",
    broker=settings.celery_broker_url,
    backend=settings.celery_broker_url,
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
    # Один воркер держит одну задачу. Иначе при рестарте пода теряются
    # разобранные, но не начатые задачи из локального буфера.
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    # Верхняя граница на сбор данных по одному полю за несколько сезонов.
    task_soft_time_limit=900,
    task_time_limit=1200,
    result_expires=86400,
    task_default_queue="analyze",
    task_routes={
        "agropulse.tasks.pipeline.collect_field_data": {"queue": "collect"},
        "agropulse.tasks.pipeline.analyze_field": {"queue": "analyze"},
        # Полный цикл начинается со сбора, поэтому идёт в сетевую очередь.
        "agropulse.tasks.pipeline.process_field": {"queue": "collect"},
    },
)
