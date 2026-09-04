"""Прогресс обработки: запись в базу и публикация в шину событий.

Пользователь видит девять стадий пайплайна и продвижение по каждому полю
отдельно. Состояние хранится дважды и с разной целью:

* таблица `jobs` — источник истины. Клиент, подключившийся к середине
  обработки или перезагрузивший страницу, получает полную картину;
* Redis pub/sub — оперативные уведомления. Через него события доходят до
  SSE-потока. Канал выбран вместо памяти процесса намеренно: реплик API может
  быть несколько, и поток обязан работать на любой из них.

Отказ шины не должен ломать обработку: прогресс — это информирование,
а не часть расчёта.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

import redis
from sqlalchemy.dialects.postgresql import insert as pg_insert

from agropulse.config import get_settings
from agropulse.db.models import Job, JobStatus, PipelineStage
from agropulse.db.session import session_scope

logger = logging.getLogger(__name__)

# Человекочитаемые названия стадий. Показываются пользователю как есть.
STAGE_TITLES: dict[PipelineStage, str] = {
    PipelineStage.SEARCH_SCENES: "Поиск спутниковых сцен",
    PipelineStage.CLOUD_MASKING: "Фильтрация облаков и теней",
    PipelineStage.INDICES: "Расчёт индексов",
    PipelineStage.WEATHER: "Получение погоды",
    PipelineStage.TIMESERIES: "Построение временного ряда",
    PipelineStage.GAP_FILLING: "Восстановление пропусков",
    PipelineStage.ANOMALIES: "Поиск аномалий",
    PipelineStage.RISK_FORECAST: "Расчёт риска и прогноза",
    PipelineStage.VISUALIZATION: "Подготовка визуализаций",
}

STAGE_ORDER: list[PipelineStage] = list(STAGE_TITLES)

_redis_client: redis.Redis | None = None


def channel(project_id: uuid.UUID | str) -> str:
    return f"agropulse:progress:{project_id}"


def _get_redis() -> redis.Redis | None:
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = redis.Redis.from_url(
                get_settings().redis_cache_url, decode_responses=True, socket_timeout=2
            )
        except Exception as exc:
            logger.warning("Шина прогресса недоступна: %s", exc)
            return None
    return _redis_client


def publish(project_id: uuid.UUID | str, event: dict) -> None:
    """Отправить событие в шину. Ошибка публикации не прерывает обработку."""
    client = _get_redis()
    if client is None:
        return
    try:
        client.publish(channel(project_id), json.dumps(event, ensure_ascii=False, default=str))
    except Exception as exc:
        logger.debug("Публикация события не удалась: %s", exc)


def report(
    project_id: uuid.UUID,
    field_id: uuid.UUID,
    stage: PipelineStage,
    status: JobStatus,
    progress: float = 0.0,
    message: str | None = None,
    error: str | None = None,
) -> None:
    """Зафиксировать состояние стадии и оповестить подписчиков.

    Запись идёт upsert'ом по (field_id, stage): повторный прогон задачи
    обновляет строку, а не создаёт вторую.
    """
    now = datetime.now(timezone.utc)
    values = {
        "id": uuid.uuid4(),
        "project_id": project_id,
        "field_id": field_id,
        "stage": stage,
        "status": status,
        "progress": progress,
        "message": message,
        "error": error,
        "started_at": now if status == JobStatus.RUNNING else None,
        "finished_at": now if status in (JobStatus.DONE, JobStatus.FAILED) else None,
    }

    try:
        with session_scope() as db:
            statement = pg_insert(Job).values(**values)
            statement = statement.on_conflict_do_update(
                constraint="uq_job_field_stage",
                set_={
                    "status": statement.excluded.status,
                    "progress": statement.excluded.progress,
                    "message": statement.excluded.message,
                    "error": statement.excluded.error,
                    "finished_at": statement.excluded.finished_at,
                },
            )
            db.execute(statement)
    except Exception as exc:
        logger.warning("Не удалось записать прогресс стадии %s: %s", stage.value, exc)

    publish(
        project_id,
        {
            "type": "stage",
            "field_id": str(field_id),
            "stage": stage.value,
            "stage_title": STAGE_TITLES[stage],
            "stage_index": STAGE_ORDER.index(stage) + 1,
            "stage_total": len(STAGE_ORDER),
            "status": status.value,
            "progress": progress,
            "message": message,
            "error": error,
            "at": now.isoformat(),
        },
    )


class StageTracker:
    """Контекст выполнения одной стадии.

    Берёт на себя отметки о начале и завершении и, что важнее, гарантирует
    отметку об ошибке: упавшая стадия должна быть видна пользователю,
    а не молча оборвать поток событий.
    """

    def __init__(self, project_id: uuid.UUID, field_id: uuid.UUID, stage: PipelineStage):
        self.project_id = project_id
        self.field_id = field_id
        self.stage = stage

    def __enter__(self) -> StageTracker:
        report(self.project_id, self.field_id, self.stage, JobStatus.RUNNING, 0.0)
        return self

    def message(self, text: str, progress: float = 0.5) -> None:
        report(self.project_id, self.field_id, self.stage, JobStatus.RUNNING, progress, text)

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if exc_type is None:
            report(self.project_id, self.field_id, self.stage, JobStatus.DONE, 1.0)
        else:
            report(
                self.project_id,
                self.field_id,
                self.stage,
                JobStatus.FAILED,
                1.0,
                error=str(exc)[:500],
            )
        return False


def field_finished(project_id: uuid.UUID, field_id: uuid.UUID, status: str, summary: dict) -> None:
    """Сообщить, что поле обработано целиком.

    Позволяет интерфейсу открывать готовые поля, не дожидаясь остальных.
    """
    publish(
        project_id,
        {
            "type": "field_done",
            "field_id": str(field_id),
            "status": status,
            "summary": summary,
            "at": datetime.now(timezone.utc).isoformat(),
        },
    )
