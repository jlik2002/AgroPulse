"""Хранение сведений о сформированных документах.

Сам документ лежит в объектном хранилище, здесь — только его описание.
Строка существует ради списка: заключение по хозяйству живёт дольше момента
скачивания, и к нему возвращаются.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from agropulse.db.models import GeneratedReport


class GeneratedReportRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_storage_key(self, storage_key: str) -> GeneratedReport | None:
        return self._session.scalar(
            select(GeneratedReport).where(GeneratedReport.storage_key == storage_key)
        )

    def list_for_project(self, project_id: uuid.UUID) -> list[GeneratedReport]:
        """Все документы проекта, свежие первыми."""
        return list(
            self._session.scalars(
                select(GeneratedReport)
                .where(GeneratedReport.project_id == project_id)
                .order_by(GeneratedReport.created_at.desc())
            ).all()
        )

    def list_for_farm(self, farm_id: uuid.UUID) -> list[GeneratedReport]:
        """Документы хозяйства: заключения по нему и отчёты по его полям.

        Отчёт по полю показывается в карточке хозяйства намеренно — человек
        ищет документ там, где смотрел объект, а не в общем списке проекта.
        """
        return list(
            self._session.scalars(
                select(GeneratedReport)
                .where(GeneratedReport.farm_id == farm_id)
                .order_by(GeneratedReport.created_at.desc())
            ).all()
        )

    def save(self, report: GeneratedReport) -> GeneratedReport:
        """Записать документ, заменив прежний с тем же ключом хранения.

        Ключ объекта в S3 вычисляется по составу документа, поэтому повторная
        сборка с теми же параметрами перезаписывает файл. Вторая строка на тот
        же ключ указывала бы на уже несуществующую версию.
        """
        existing = self.get_by_storage_key(report.storage_key)
        if existing is not None:
            existing.title = report.title
            existing.filename = report.filename
            existing.params = report.params
            existing.pages = report.pages
            existing.size_bytes = report.size_bytes
            existing.farm_id = report.farm_id
            existing.field_id = report.field_id
            self._session.flush()
            return existing

        self._session.add(report)
        self._session.flush()
        return report
