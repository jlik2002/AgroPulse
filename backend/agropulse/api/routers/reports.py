"""Выгрузка результатов: CSV и PDF-отчёты.

Роутер занимается только HTTP: подбирает заголовки и отдаёт готовый документ.
Сбор данных, рендер и сохранение в объектное хранилище выполняет
`services/reports.py`.
"""

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Query, Response

from agropulse.api.deps import ReportServiceDep
from agropulse.services.reports import ReportDocument

router = APIRouter(tags=["reports"])

CLIENT_QUERY = Query(default=None, description="Название хозяйства для обложки")


def _as_response(document: ReportDocument) -> Response:
    # RFC 5987: имя файла с кириллицей должно уехать в кодированном виде,
    # иначе браузер получит нечитаемое название.
    return Response(
        content=document.content,
        media_type=document.media_type,
        headers={
            "Content-Disposition": (
                f"attachment; filename*=UTF-8''{quote(document.filename)}"
            )
        },
    )


@router.get("/fields/{field_id}/export.csv")
def export_field_csv(field_id: uuid.UUID, service: ReportServiceDep) -> Response:
    """Временной ряд поля в CSV."""
    return _as_response(service.field_csv(field_id))


@router.get("/projects/{project_id}/export.csv")
def export_project_csv(project_id: uuid.UUID, service: ReportServiceDep) -> Response:
    """Временные ряды всех полей проекта в одном CSV."""
    return _as_response(service.project_csv(project_id))


@router.get("/fields/{field_id}/report.pdf")
def export_field_pdf(
    field_id: uuid.UUID, service: ReportServiceDep, client: str | None = CLIENT_QUERY
) -> Response:
    """Аналитический отчёт по полю."""
    return _as_response(service.field_pdf(field_id, client))


@router.get("/projects/{project_id}/report.pdf")
def export_project_pdf(
    project_id: uuid.UUID, service: ReportServiceDep, client: str | None = CLIENT_QUERY
) -> Response:
    """Сводный отчёт по хозяйству с очередью на осмотр."""
    return _as_response(service.project_pdf(project_id, client))
