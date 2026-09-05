"""Схемы сформированных документов.

Содержимое здесь не отдаётся — только описание: что за документ, к чему
относится, сколько страниц и когда собран. Файл забирается отдельным
запросом, иначе список отчётов возил бы мегабайты на каждое открытие
карточки хозяйства.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from agropulse.db.models import ReportKind


class GeneratedReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: ReportKind
    title: str
    filename: str
    # Адресат документа. Заполнено либо хозяйство, либо поле, либо ни одно
    # из двух — и тогда документ относится ко всему проекту.
    project_id: uuid.UUID
    farm_id: uuid.UUID | None
    field_id: uuid.UUID | None
    pages: int | None
    size_bytes: int | None
    created_at: datetime
