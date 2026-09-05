"""Прогресс обработки: запись в базу и публикация в шину событий.

Пользователь видит девять стадий пайплайна и продвижение по каждому полю
отдельно. Состояние хранится дважды и с разной целью:

* таблица `jobs` — источник истины. Клиент, подключившийся к середине
  обработки или перезагрузивший страницу, получает полную картину;
* Redis pub/sub — оперативные уведомления, доходящие до SSE-потока.

Каждая отметка о прогрессе фиксируется собственной короткой транзакцией и
не входит в транзакцию бизнес-операции. Это сделано намеренно: транзакция
задачи сбора живёт минуты, и прогресс, записанный внутри неё, стал бы виден
пользователю только по её завершении — то есть тогда, когда он уже не нужен.

Отказ шины или базы прогресса не должен ломать обработку: прогресс — это
информирование, а не часть расчёта.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from types import TracebackType

from sqlalchemy.exc import SQLAlchemyError

from agropulse.db.models import Job, JobStatus, PipelineStage
from agropulse.db.uow import UnitOfWork, unit_of_work
from agropulse.events import publish_progress

logger = logging.getLogger(__name__)

# Человекочитаемые названия стадий. Показываются пользователю как есть.
STAGE_TITLES: dict[PipelineStage, str] = {
    PipelineStage.SEARCH_SCENES: "Поиск спутниковых сцен",
    PipelineStage.CLOUD_MASKING: "Фильтрация облаков и теней",
    PipelineStage.INDICES: "Расчёт индексов",
    PipelineStage.RADAR: "Радарная съёмка Sentinel-1",
    PipelineStage.WEATHER: "Получение погоды",
    PipelineStage.TIMESERIES: "Построение временного ряда",
    PipelineStage.GAP_FILLING: "Восстановление пропусков",
    PipelineStage.ANOMALIES: "Поиск аномалий",
    PipelineStage.RISK_FORECAST: "Расчёт риска и прогноза",
    PipelineStage.VISUALIZATION: "Подготовка визуализаций",
}

STAGE_ORDER: list[PipelineStage] = list(STAGE_TITLES)

# Ограничение длины текста ошибки в поле, которое видит пользователь.
# Полный traceback остаётся в логах: показывать его в интерфейсе бессмысленно
# и небезопасно — он раскрывает внутреннее устройство сервиса.
MAX_ERROR_LENGTH = 500


def report(
    project_id: uuid.UUID,
    field_id: uuid.UUID,
    stage: PipelineStage,
    status: JobStatus,
    progress: float = 0.0,
    message: str | None = None,
    error: str | None = None,
    task_id: str | None = None,
) -> None:
    """Зафиксировать состояние стадии и оповестить подписчиков."""
    now = datetime.now(UTC)

    try:
        with unit_of_work() as uow:
            uow.jobs.upsert_stage(
                project_id=project_id,
                field_id=field_id,
                stage=stage,
                status=status,
                progress=progress,
                message=message,
                error=error,
                started_at=now if status == JobStatus.RUNNING else None,
                finished_at=now if status in (JobStatus.DONE, JobStatus.FAILED) else None,
                celery_task_id=task_id,
            )
    except SQLAlchemyError as exc:
        logger.warning(
            "progress_write_failed",
            extra={"stage": stage.value, "field_id": str(field_id), "error": str(exc)},
        )

    publish_progress(
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


def field_finished(
    project_id: uuid.UUID, field_id: uuid.UUID, status: str, summary: dict
) -> None:
    """Сообщить, что поле обработано целиком.

    Позволяет интерфейсу открывать готовые поля, не дожидаясь остальных.
    """
    publish_progress(
        project_id,
        {
            "type": "field_done",
            "field_id": str(field_id),
            "status": status,
            "summary": summary,
            "at": datetime.now(UTC).isoformat(),
        },
    )


class StageTracker:
    """Контекст выполнения одной стадии.

    Берёт на себя отметки о начале и завершении и, что важнее, гарантирует
    отметку об ошибке: упавшая стадия должна быть видна пользователю,
    а не молча оборвать поток событий.
    """

    def __init__(
        self,
        project_id: uuid.UUID,
        field_id: uuid.UUID,
        stage: PipelineStage,
        task_id: str | None = None,
    ) -> None:
        self._project_id = project_id
        self._field_id = field_id
        self._stage = stage
        self._task_id = task_id
        # Последнее сообщение стадии переносится в отметку о завершении.
        # Иначе в списке стадий у готового поля оставались пустые подписи:
        # запись со статусом DONE затирала текст, ради которого стадия и
        # сообщала о себе («найдено 24 сцены», «18 снимков пригодны»).
        self._last_message: str | None = None

    def __enter__(self) -> StageTracker:
        report(
            self._project_id,
            self._field_id,
            self._stage,
            JobStatus.RUNNING,
            0.0,
            task_id=self._task_id,
        )
        return self

    def message(self, text: str, progress: float = 0.5) -> None:
        self._last_message = text
        report(
            self._project_id,
            self._field_id,
            self._stage,
            JobStatus.RUNNING,
            progress,
            text,
            task_id=self._task_id,
        )

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        if exc_type is None:
            report(
                self._project_id,
                self._field_id,
                self._stage,
                JobStatus.DONE,
                1.0,
                self._last_message,
                task_id=self._task_id,
            )
        else:
            report(
                self._project_id,
                self._field_id,
                self._stage,
                JobStatus.FAILED,
                1.0,
                error=str(exc)[:MAX_ERROR_LENGTH],
                task_id=self._task_id,
            )
        return False


def build_snapshot(uow: UnitOfWork, project_id: uuid.UUID) -> dict:
    """Текущее состояние стадий по всем полям проекта.

    Уходит первым сообщением SSE-потока: клиент, подключившийся к середине
    обработки, сразу видит полную картину, а не ждёт следующего события.
    """
    by_field: dict[str, list[dict]] = {}
    for job in uow.jobs.list_for_project(project_id):
        by_field.setdefault(str(job.field_id), []).append(_stage_view(job))

    for stages in by_field.values():
        stages.sort(key=lambda item: item["stage_index"])

    return {
        "project_id": str(project_id),
        "stage_total": len(STAGE_ORDER),
        "stages": [
            {"stage": stage.value, "title": STAGE_TITLES[stage], "index": index + 1}
            for index, stage in enumerate(STAGE_ORDER)
        ],
        "fields": by_field,
    }


def _stage_view(job: Job) -> dict:
    return {
        "stage": job.stage.value,
        "stage_title": STAGE_TITLES[job.stage],
        "stage_index": STAGE_ORDER.index(job.stage) + 1,
        "status": job.status.value,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
    }
