"""Сценарии выгрузки результатов: CSV и PDF.

Отчёт собирается синхронно: генерация занимает единицы секунд, и очередь ради
неё усложнила бы сценарий скачивания без выигрыша. Готовый PDF кладётся в
объектное хранилище, чтобы повторное скачивание не пересобирало его заново.

Сборщики отчётов данные не читают — они получают их отсюда. Поэтому сводный
отчёт по хозяйству обходится тремя запросами вместо трёх на каждое поле.

Каждый собранный документ регистрируется в базе. До появления хозяйств отчёт
был действием: собрали, отдали в поток, след остался только объектом в
хранилище с вычисляемым именем. Заключение по хозяйству живёт дольше момента
скачивания — на него ссылаются и его перечитывают, поэтому у документа
появились владелец, дата и место в списке.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime

from agropulse.analytics import farm as farm_analytics
from agropulse.db.models import GeneratedReport, ReportKind
from agropulse.db.uow import UnitOfWork
from agropulse.errors import (
    FarmNotFoundError,
    FieldNotFoundError,
    ProjectNotFoundError,
    ReportNotFoundError,
)
from agropulse.reports import csv_export, pdf
from agropulse.reports.data import (
    FarmData,
    FieldData,
    ProjectData,
    RegistryData,
    RegistryEntry,
)
from agropulse.storage import s3

logger = logging.getLogger(__name__)

CSV_MEDIA_TYPE = "text/csv; charset=utf-8"
PDF_MEDIA_TYPE = "application/pdf"

# Excel определяет кодировку CSV по метке порядка байтов. Без неё файл
# с кириллицей открывается нечитаемым, и пользователь считает выгрузку сломанной.
BOM = "﻿"


def _sections_key(sections: set[str]) -> str:
    """Короткий устойчивый ключ набора разделов.

    Отчёт кэшируется по составу разделов, а их 127 сочетаний. Полное
    перечисление в имени объекта дало бы длинные ключи и столько же файлов
    на поле; хэш оставляет то же свойство «разный состав — разный объект»
    при постоянной длине имени.
    """
    if not sections:
        return "default"
    digest = hashlib.sha1("|".join(sorted(sections)).encode("utf-8")).hexdigest()
    return digest[:10]


@dataclass(slots=True)
class ReportDocument:
    filename: str
    content: str | bytes
    media_type: str
    # Разметку страниц знает только вёрстка PDF; для CSV остаётся пусто.
    pages: int | None = None
    # Ключ раздела и страница, с которой он начинается, в порядке документа.
    sections: list[tuple[str, int]] = dataclass_field(default_factory=list)


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

    def farm_csv(self, project_id: uuid.UUID, farm_id: uuid.UUID) -> ReportDocument:
        data = self._load_farm(project_id, farm_id)
        return ReportDocument(
            filename=f"{data.farm.name}.csv",
            content=BOM + csv_export.export_fields(data.fields),
            media_type=CSV_MEDIA_TYPE,
        )

    def registry_csv(self, project_id: uuid.UUID) -> ReportDocument:
        data = self._load_registry(project_id)
        stamp = datetime.now().strftime("%Y-%m-%d")
        return ReportDocument(
            filename=f"Реестр поддержки {stamp}.csv",
            content=BOM + csv_export.export_registry(data),
            media_type=CSV_MEDIA_TYPE,
        )

    # ------------------------------------------------------------------
    # PDF
    # ------------------------------------------------------------------

    def field_pdf(
        self,
        field_id: uuid.UUID,
        client: str | None = None,
        sections: str | None = None,
    ) -> ReportDocument:
        data = self._load_field(field_id)
        chosen = pdf.resolve_sections(sections)
        document = pdf.build_field_report(data, client, chosen)
        # Ключ включает состав разделов: два отчёта по одному полю с разным
        # набором разделов — разные документы, и затирать один другим нельзя.
        filename = f"{data.field.name}.pdf"
        self._publish(
            key=f"reports/field/{field_id}-{_sections_key(chosen)}.pdf",
            document=document,
            kind=ReportKind.FIELD,
            title=f"Отчёт по полю «{data.field.name}»",
            filename=filename,
            project_id=data.field.project_id,
            farm_id=data.field.farm_id,
            field_id=data.field.id,
            params={"sections": sorted(chosen)},
        )
        return ReportDocument(
            filename=filename,
            content=document.content,
            media_type=PDF_MEDIA_TYPE,
            pages=document.pages,
            sections=document.sections,
        )

    def project_pdf(self, project_id: uuid.UUID, client: str | None = None) -> ReportDocument:
        data = self._load_project(project_id)
        document = pdf.build_project_report(data, client)
        stamp = datetime.now().strftime("%Y-%m-%d")
        filename = f"Сводный отчёт {stamp}.pdf"
        self._publish(
            key=f"reports/project/{project_id}.pdf",
            document=document,
            kind=ReportKind.PROJECT,
            title="Сводный отчёт по полям проекта",
            filename=filename,
            project_id=project_id,
            params={"client": client} if client else None,
        )
        return ReportDocument(
            filename=filename,
            content=document.content,
            media_type=PDF_MEDIA_TYPE,
            pages=document.pages,
            sections=document.sections,
        )

    def farm_pdf(self, project_id: uuid.UUID, farm_id: uuid.UUID) -> ReportDocument:
        """Заключение о состоянии угодий хозяйства за период проекта."""
        data = self._load_farm(project_id, farm_id)
        document = pdf.build_farm_report(data)
        filename = f"Заключение — {data.farm.name}.pdf"
        self._publish(
            # Ключ включает проект: справочник хозяйств общий, и одно
            # предприятие даёт разные заключения за разные периоды.
            key=f"reports/farm/{project_id}-{farm_id}.pdf",
            document=document,
            kind=ReportKind.FARM,
            title=f"Заключение по хозяйству «{data.farm.name}»",
            filename=filename,
            project_id=project_id,
            farm_id=data.farm.id,
            params={
                "support_need_score": data.assessment.support_need_score,
                "category": data.assessment.category.value,
                "trust": data.assessment.trust.value,
            },
        )
        return ReportDocument(
            filename=filename,
            content=document.content,
            media_type=PDF_MEDIA_TYPE,
            pages=document.pages,
            sections=document.sections,
        )

    def registry_pdf(self, project_id: uuid.UUID, client: str | None = None) -> ReportDocument:
        """Реестр приоритетной государственной поддержки."""
        data = self._load_registry(project_id)
        document = pdf.build_registry_report(data, client)
        stamp = datetime.now().strftime("%Y-%m-%d")
        filename = f"Реестр поддержки {stamp}.pdf"
        self._publish(
            key=f"reports/registry/{project_id}.pdf",
            document=document,
            kind=ReportKind.REGISTRY,
            title="Реестр приоритетной государственной поддержки",
            filename=filename,
            project_id=project_id,
            params={"client": client, "farms": len(data.rows) + len(data.undetermined)},
        )
        return ReportDocument(
            filename=filename,
            content=document.content,
            media_type=PDF_MEDIA_TYPE,
            pages=document.pages,
            sections=document.sections,
        )

    # ------------------------------------------------------------------
    # Список сформированных документов
    # ------------------------------------------------------------------

    def list_for_project(self, project_id: uuid.UUID) -> list[GeneratedReport]:
        if not self._uow.projects.exists(project_id):
            raise ProjectNotFoundError(project_id=str(project_id))
        return self._uow.reports.list_for_project(project_id)

    def list_for_farm(self, farm_id: uuid.UUID) -> list[GeneratedReport]:
        if self._uow.farms.get(farm_id) is None:
            raise FarmNotFoundError(farm_id=str(farm_id))
        return self._uow.reports.list_for_farm(farm_id)

    def download(self, report_id: uuid.UUID) -> ReportDocument:
        """Отдать ранее собранный документ из хранилища.

        Повторное скачивание не пересобирает отчёт: содержимое уже лежит в S3,
        а пересборка дала бы другой документ, если данные с тех пор изменились,
        — и ссылка на «тот самый файл» перестала бы значить что-либо.
        """
        report = self._uow.session.get(GeneratedReport, report_id)
        if report is None:
            raise ReportNotFoundError(report_id=str(report_id))
        return ReportDocument(
            filename=report.filename,
            content=s3.get_object(report.storage_key),
            media_type=PDF_MEDIA_TYPE,
            pages=report.pages,
        )

    # ------------------------------------------------------------------

    def _load_farm(self, project_id: uuid.UUID, farm_id: uuid.UUID) -> FarmData:
        farm = self._uow.farms.get(farm_id)
        if farm is None:
            raise FarmNotFoundError(farm_id=str(farm_id))
        project = self._uow.projects.get(project_id)
        if project is None:
            raise ProjectNotFoundError(project_id=str(project_id))

        fields = self._uow.fields.list_for_farm(farm_id, project_id)
        field_ids = [field.id for field in fields]
        observations = self._uow.observations.list_for_fields(field_ids)
        radar = self._uow.radar.list_for_fields(field_ids)
        anomalies = self._uow.anomalies.list_for_fields(field_ids)
        forecasts = self._uow.forecasts.get_for_fields(field_ids)

        return FarmData(
            farm=farm,
            period_from=project.period_from,
            period_to=project.period_to,
            assessment=farm_analytics.assess(
                [
                    farm_analytics.field_input(
                        field, anomalies.get(field.id, []), forecasts.get(field.id)
                    )
                    for field in fields
                ]
            ),
            fields=[
                FieldData(
                    field=field,
                    period_from=project.period_from,
                    period_to=project.period_to,
                    observations=observations.get(field.id, []),
                    radar=radar.get(field.id, []),
                    anomalies=anomalies.get(field.id, []),
                    forecast_run=forecasts.get(field.id),
                )
                for field in fields
            ],
        )

    def _load_registry(self, project_id: uuid.UUID) -> RegistryData:
        """Реестр целиком: четыре запроса независимо от числа хозяйств.

        Наблюдения не читаются вовсе — в строке реестра их нет, а состояние
        поля уже сведено в его статус и балл.
        """
        project = self._uow.projects.get(project_id)
        if project is None:
            raise ProjectNotFoundError(project_id=str(project_id))

        farms = {farm.id: farm for farm in self._uow.farms.list_all()}
        fields = self._uow.fields.list_for_project(project_id)
        field_ids = [field.id for field in fields]
        anomalies = self._uow.anomalies.list_for_fields(field_ids)
        forecasts = self._uow.forecasts.get_for_fields(field_ids)

        # В реестр идут только хозяйства с полями в этом проекте: у остальных
        # период наблюдения другой, и оценивать их здесь нечем.
        by_farm: dict[uuid.UUID, list] = {}
        unassigned = []
        for field in fields:
            if field.farm_id in farms:
                by_farm.setdefault(field.farm_id, []).append(field)
            else:
                unassigned.append(field)

        entries = [
            RegistryEntry(
                farm=farms[farm_id],
                assessment=farm_analytics.assess(
                    [
                        farm_analytics.field_input(
                            field, anomalies.get(field.id, []), forecasts.get(field.id)
                        )
                        for field in farm_fields
                    ]
                ),
            )
            for farm_id, farm_fields in by_farm.items()
        ]

        ranked = sorted(
            (
                entry
                for entry in entries
                if entry.assessment.support_need_score is not None
                and entry.assessment.category
                is not farm_analytics.ReviewCategory.UNDETERMINED
            ),
            key=lambda entry: entry.assessment.support_need_score or 0.0,
            reverse=True,
        )
        for position, entry in enumerate(ranked, start=1):
            entry.rank = position

        return RegistryData(
            project_id=project.id,
            period_from=project.period_from,
            period_to=project.period_to,
            rows=ranked,
            undetermined=[entry for entry in entries if entry.rank is None],
            unassigned_fields=unassigned,
        )

    def _load_field(self, field_id: uuid.UUID) -> FieldData:
        field = self._uow.fields.get_with_project(field_id)
        if field is None:
            raise FieldNotFoundError(field_id=str(field_id))
        return FieldData(
            field=field,
            period_from=field.project.period_from,
            period_to=field.project.period_to,
            observations=self._uow.observations.list_for_field(field_id),
            radar=self._uow.radar.list_for_field(field_id),
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
        radar = self._uow.radar.list_for_fields(field_ids)
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
                    radar=radar.get(field.id, []),
                    anomalies=anomalies.get(field.id, []),
                    forecast_run=forecasts.get(field.id),
                )
                for field in fields
            ],
        )

    def _publish(
        self,
        *,
        key: str,
        document: pdf.RenderedReport,
        kind: ReportKind,
        title: str,
        filename: str,
        project_id: uuid.UUID,
        farm_id: uuid.UUID | None = None,
        field_id: uuid.UUID | None = None,
        params: dict | None = None,
    ) -> None:
        """Сохранить документ в хранилище и зарегистрировать его в базе.

        Отказ хранилища не мешает пользователю скачать файл: документ уже
        собран и уходит в ответ независимо от результата сохранения. Но строки
        в базе в этом случае не появляется — она указывала бы на объект,
        которого нет, и повторное скачивание из списка отдало бы ошибку.
        """
        try:
            s3.put_object(key, document.content, PDF_MEDIA_TYPE)
        except Exception as exc:
            logger.warning("report_store_failed", extra={"key": key, "error": str(exc)})
            return

        self._uow.reports.save(
            GeneratedReport(
                project_id=project_id,
                farm_id=farm_id,
                field_id=field_id,
                kind=kind,
                title=title,
                filename=filename,
                storage_key=key,
                params=params,
                pages=document.pages,
                size_bytes=len(document.content),
            )
        )
        self._uow.commit()
