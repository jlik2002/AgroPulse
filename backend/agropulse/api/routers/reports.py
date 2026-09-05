"""Выгрузка результатов: CSV и PDF-отчёты трёх уровней.

Поле, хозяйство, реестр — три адресата, и путь документа называет того,
кому он адресован. Отчёт по полю смотрит агроном, заключение по хозяйству —
комиссия, реестр — распорядитель средств.

Роутер занимается только HTTP: подбирает заголовки и отдаёт готовый документ.
Сбор данных, рендер, сохранение в объектное хранилище и регистрацию документа
выполняет `services/reports.py`.
"""

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Query, Response

from agropulse.api.deps import ReportServiceDep
from agropulse.schemas.report import GeneratedReportRead
from agropulse.services.reports import ReportDocument

router = APIRouter(tags=["reports"])

CLIENT_QUERY = Query(default=None, description="Название хозяйства для обложки")
SECTIONS_QUERY = Query(
    default=None,
    description=(
        "Разделы отчёта через запятую: summary, state, dynamics, anomalies, "
        "forecast, quality, table. По умолчанию включены все, кроме table."
    ),
)


def _as_response(document: ReportDocument) -> Response:
    # RFC 5987: имя файла с кириллицей должно уехать в кодированном виде,
    # иначе браузер получит нечитаемое название.
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(document.filename)}",
    }
    exposed = ["Content-Disposition"]

    if document.pages is not None:
        # Интерфейс показывает число страниц на карточке готового файла.
        # Из тела PDF его не достать, поэтому отдаём заголовком.
        headers["X-Report-Pages"] = str(document.pages)
        exposed.append("X-Report-Pages")

    if document.sections:
        # Оглавление: ключ раздела и номер страницы, где он начинается.
        # Ключи латинские и цифры — заголовок остаётся ASCII, кодировать
        # нечего. Названия разделов интерфейс знает сам.
        headers["X-Report-Sections"] = ",".join(
            f"{key}:{page}" for key, page in document.sections
        )
        exposed.append("X-Report-Sections")

    headers["Access-Control-Expose-Headers"] = ", ".join(exposed)
    return Response(content=document.content, media_type=document.media_type, headers=headers)


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
    field_id: uuid.UUID,
    service: ReportServiceDep,
    client: str | None = CLIENT_QUERY,
    sections: str | None = SECTIONS_QUERY,
) -> Response:
    """Аналитический отчёт по полю с выбранным составом разделов."""
    return _as_response(service.field_pdf(field_id, client, sections))


@router.get("/projects/{project_id}/report.pdf")
def export_project_pdf(
    project_id: uuid.UUID, service: ReportServiceDep, client: str | None = CLIENT_QUERY
) -> Response:
    """Сводный отчёт по хозяйству с очередью на осмотр."""
    return _as_response(service.project_pdf(project_id, client))


# ----------------------------------------------------------------------
# Хозяйство и реестр
# ----------------------------------------------------------------------


@router.get("/farms/{farm_id}/export.csv")
def export_farm_csv(farm_id: uuid.UUID, service: ReportServiceDep) -> Response:
    """Временные ряды всех полей хозяйства в одном CSV."""
    return _as_response(service.farm_csv(farm_id))


@router.get("/farms/{farm_id}/report.pdf")
def export_farm_pdf(farm_id: uuid.UUID, service: ReportServiceDep) -> Response:
    """Информационно-аналитическое заключение о состоянии угодий хозяйства."""
    return _as_response(service.farm_pdf(farm_id))


@router.get("/projects/{project_id}/registry.csv")
def export_registry_csv(project_id: uuid.UUID, service: ReportServiceDep) -> Response:
    """Реестр хозяйств в машинно-читаемом виде."""
    return _as_response(service.registry_csv(project_id))


@router.get("/projects/{project_id}/registry.pdf")
def export_registry_pdf(
    project_id: uuid.UUID, service: ReportServiceDep, client: str | None = CLIENT_QUERY
) -> Response:
    """Реестр приоритетной государственной поддержки сельхозпроизводителей."""
    return _as_response(service.registry_pdf(project_id, client))


# ----------------------------------------------------------------------
# Ранее сформированные документы
# ----------------------------------------------------------------------


@router.get("/projects/{project_id}/reports", response_model=list[GeneratedReportRead])
def list_project_reports(
    project_id: uuid.UUID, service: ReportServiceDep
) -> list[GeneratedReportRead]:
    """Все документы проекта, свежие первыми."""
    return [
        GeneratedReportRead.model_validate(report)
        for report in service.list_for_project(project_id)
    ]


@router.get("/farms/{farm_id}/reports", response_model=list[GeneratedReportRead])
def list_farm_reports(
    farm_id: uuid.UUID, service: ReportServiceDep
) -> list[GeneratedReportRead]:
    """Документы хозяйства: заключения по нему и отчёты по его полям."""
    return [
        GeneratedReportRead.model_validate(report)
        for report in service.list_for_farm(farm_id)
    ]


@router.get("/reports/{report_id}/download")
def download_report(report_id: uuid.UUID, service: ReportServiceDep) -> Response:
    """Скачать ранее собранный документ.

    Отдаётся сохранённый файл, а не пересобранный: если данные с тех пор
    изменились, пересборка дала бы другой документ, и ссылка на «тот самый
    отчёт» перестала бы значить что-либо.
    """
    return _as_response(service.download(report_id))
