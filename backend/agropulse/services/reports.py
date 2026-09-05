"""Сценарии выгрузки результатов: CSV и PDF.

Отчёт собирается синхронно: генерация занимает единицы секунд, и очередь ради
неё усложнила бы сценарий скачивания без выигрыша. Готовый PDF кладётся в
объектное хранилище, чтобы повторное скачивание не пересобирало его заново.

Сборщики отчётов данные не читают — они получают их отсюда. Поэтому сводный
отчёт по хозяйству обходится тремя запросами вместо трёх на каждое поле.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from agropulse.db.uow import UnitOfWork
from agropulse.errors import FieldNotFoundError, ProjectNotFoundError
from agropulse.reports import csv_export, pdf
from agropulse.reports.data import FieldData, ProjectData
from agropulse.storage import s3

logger = logging.getLogger(__name__)

CSV_MEDIA_TYPE = "text/csv; charset=utf-8"
PDF_MEDIA_TYPE = "application/pdf"

# Excel определяет кодировку CSV по метке порядка байтов. Без неё файл
# с кириллицей открывается нечитаемым, и пользователь считает выгрузку сломанной.
BOM = "﻿"


@dataclass(slots=True)
class ReportDocument:
    filename: str
    content: str | bytes
    media_type: str


class ReportService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    # ------------------------------------------------------------------
    # CSV
    # ------------------------------------------------------------------

    def field_csv(self, field_id: uuid.UUID) -> ReportDocument:
        data = self._load_field(field_id)
        return ReportDocument(
            filename=f"{data.field.name}.csv",
            content=BOM + csv_export.export_fields([data]),
            media_type=CSV_MEDIA_TYPE,
        )

    def project_csv(self, project_id: uuid.UUID) -> ReportDocument:
        data = self._load_project(project_id)
        return ReportDocument(
            filename="agropulse-export.csv",
            content=BOM + csv_export.export_fields(data.fields),
            media_type=CSV_MEDIA_TYPE,
        )

    # ------------------------------------------------------------------
    # PDF
    # ------------------------------------------------------------------

    def field_pdf(self, field_id: uuid.UUID, client: str | None = None) -> ReportDocument:
        data = self._load_field(field_id)
        document = pdf.build_field_report(data, client)
        self._store(f"reports/field/{field_id}.pdf", document)
        return ReportDocument(
            filename=f"{data.field.name}.pdf",
            content=document,
            media_type=PDF_MEDIA_TYPE,
        )

    def project_pdf(self, project_id: uuid.UUID, client: str | None = None) -> ReportDocument:
        data = self._load_project(project_id)
        document = pdf.build_project_report(data, client)
        self._store(f"reports/project/{project_id}.pdf", document)
        stamp = datetime.now().strftime("%Y-%m-%d")
        return ReportDocument(
            filename=f"Сводный отчёт {stamp}.pdf",
            content=document,
            media_type=PDF_MEDIA_TYPE,
        )

    # ------------------------------------------------------------------

    def _load_field(self, field_id: uuid.UUID) -> FieldData:
        field = self._uow.fields.get_with_project(field_id)
        if field is None:
            raise FieldNotFoundError(field_id=str(field_id))
        return FieldData(
            field=field,
            period_from=field.project.period_from,
            period_to=field.project.period_to,
            observations=self._uow.observations.list_for_field(field_id),
            anomalies=self._uow.anomalies.list_for_field(field_id),
            forecast_run=self._uow.forecasts.get_for_field(field_id),
        )

    def _load_project(self, project_id: uuid.UUID) -> ProjectData:
        project = self._uow.projects.get(project_id)
        if project is None:
            raise ProjectNotFoundError(project_id=str(project_id))

        fields = self._uow.fields.list_for_project(project_id)
        field_ids = [field.id for field in fields]
        observations = self._uow.observations.list_for_fields(field_ids)
        anomalies = self._uow.anomalies.list_for_fields(field_ids)
        forecasts = self._uow.forecasts.get_for_fields(field_ids)

        return ProjectData(
            project_id=project.id,
            period_from=project.period_from,
            period_to=project.period_to,
            fields=[
                FieldData(
                    field=field,
                    period_from=project.period_from,
                    period_to=project.period_to,
                    observations=observations.get(field.id, []),
                    anomalies=anomalies.get(field.id, []),
                    forecast_run=forecasts.get(field.id),
                )
                for field in fields
            ],
        )

    @staticmethod
    def _store(key: str, document: bytes) -> None:
        """Сохранить отчёт в объектное хранилище.

        Отказ хранилища не должен мешать пользователю скачать файл: документ
        уже сформирован и уходит в ответ независимо от результата сохранения.
        """
        try:
            s3.put_object(key, document, PDF_MEDIA_TYPE)
        except Exception as exc:
            logger.warning("report_store_failed", extra={"key": key, "error": str(exc)})
