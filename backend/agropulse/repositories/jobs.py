"""Хранение прогресса обработки по стадиям."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from agropulse.db.models import Job, JobStatus, PipelineStage


class JobRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_for_project(self, project_id: uuid.UUID) -> list[Job]:
        return list(
            self._session.scalars(select(Job).where(Job.project_id == project_id)).all()
        )

    def upsert_stage(
        self,
        *,
        project_id: uuid.UUID,
        field_id: uuid.UUID,
        stage: PipelineStage,
        status: JobStatus,
        progress: float,
        message: str | None,
        error: str | None,
        started_at: datetime | None,
        finished_at: datetime | None,
        celery_task_id: str | None = None,
    ) -> None:
        """Записать состояние стадии.

        Upsert по (field_id, stage): повторный прогон задачи обновляет строку,
        а не создаёт вторую. `started_at` при конфликте не трогаем — время
        первого запуска стадии интереснее времени последнего.
        """
        statement = pg_insert(Job).values(
            id=uuid.uuid4(),
            project_id=project_id,
            field_id=field_id,
            stage=stage,
            status=status,
            progress=progress,
            message=message,
            error=error,
            started_at=started_at,
            finished_at=finished_at,
            celery_task_id=celery_task_id,
        )
        self._session.execute(
            statement.on_conflict_do_update(
                constraint="uq_job_field_stage",
                set_={
                    "status": statement.excluded.status,
                    "progress": statement.excluded.progress,
                    "message": statement.excluded.message,
                    "error": statement.excluded.error,
                    "finished_at": statement.excluded.finished_at,
                    "celery_task_id": statement.excluded.celery_task_id,
                },
            )
        )
