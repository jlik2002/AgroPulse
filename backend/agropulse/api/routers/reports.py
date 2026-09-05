"""Выгрузка результатов: CSV и PDF-отчёты.

CSV содержит только числа и признаки качества, без текстов языковой модели —
это машинно-читаемый экспорт для дальнейшей обработки.

PDF собирается синхронно: генерация занимает единицы секунд, и отдавать её
в очередь означало бы усложнить сценарий скачивания ради несущественного
выигрыша. Готовый файл кладётся в объектное хранилище, чтобы повторное
скачивание не пересобирало отчёт заново.
"""

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from agropulse.db.models import Field, Project
from agropulse.db.session import get_db
from agropulse.reports import csv_export, pdf
from agropulse.storage import s3

logger = logging.getLogger(__name__)
router = APIRouter(tags=["reports"])

CSV_MEDIA_TYPE = "text/csv; charset=utf-8"
PDF_MEDIA_TYPE = "application/pdf"


def _attachment(filename: str) -> dict[str, str]:
    # RFC 5987: имя файла с кириллицей должно уехать в кодированном виде,
    # иначе браузер получит нечитаемое название.
    from urllib.parse import quote

    return {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}


@router.get("/fields/{field_id}/export.csv")
def export_field_csv(field_id: uuid.UUID, db: Session = Depends(get_db)) -> Response:
    """Временной ряд поля в CSV."""
    content = csv_export.export_field(db, field_id)
    if content is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="поле не найдено")

    field = db.get(Field, field_id)
    return Response(
        # BOM нужен, чтобы Excel открыл файл с кириллицей в правильной кодировке.
        content="﻿" + content,
        media_type=CSV_MEDIA_TYPE,
        headers=_attachment(f"{field.name}.csv"),
    )


@router.get("/projects/{project_id}/export.csv")
def export_project_csv(project_id: uuid.UUID, db: Session = Depends(get_db)) -> Response:
    """Временные ряды всех полей проекта в одном CSV."""
    if db.get(Project, project_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="проект не найден")
    content = csv_export.export_project(db, project_id)
    return Response(
        content="﻿" + content,
        media_type=CSV_MEDIA_TYPE,
        headers=_attachment("agropulse-export.csv"),
    )


@router.get("/fields/{field_id}/report.pdf")
def export_field_pdf(
    field_id: uuid.UUID,
    client: str | None = Query(default=None, description="Название хозяйства для обложки"),
    db: Session = Depends(get_db),
) -> Response:
    """Аналитический отчёт по полю."""
    field = db.get(Field, field_id)
    if field is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="поле не найдено")

    document = pdf.build_field_report(db, field_id, client)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="поле не найдено")

    _store(f"reports/field/{field_id}.pdf", document)
    return Response(
        content=document,
        media_type=PDF_MEDIA_TYPE,
        headers=_attachment(f"{field.name}.pdf"),
    )


@router.get("/projects/{project_id}/report.pdf")
def export_project_pdf(
    project_id: uuid.UUID,
    client: str | None = Query(default=None, description="Название хозяйства для обложки"),
    db: Session = Depends(get_db),
) -> Response:
    """Сводный отчёт по хозяйству с очередью на осмотр."""
    document = pdf.build_project_report(db, project_id, client)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="проект не найден")

    _store(f"reports/project/{project_id}.pdf", document)
    stamp = datetime.now().strftime("%Y-%m-%d")
    return Response(
        content=document,
        media_type=PDF_MEDIA_TYPE,
        headers=_attachment(f"Сводный отчёт {stamp}.pdf"),
    )


def _store(key: str, document: bytes) -> None:
    """Сохранить отчёт в объектное хранилище.

    Отказ хранилища не должен мешать пользователю скачать файл: документ уже
    сформирован и уходит в ответ независимо от результата сохранения.
    """
    try:
        s3.put_object(key, document, PDF_MEDIA_TYPE)
    except Exception as exc:
        logger.warning("Отчёт %s не сохранён в хранилище: %s", key, exc)
