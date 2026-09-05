"""Схемы хозяйства и реестра приоритетной поддержки.

Балл и достоверность отдаются всегда вместе. Разделить их — значит позволить
интерфейсу показать «низкая потребность» там, где на хозяйство просто нет
снимков, а это ровно та ошибка, ради которой достоверность и считается.
"""

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agropulse.analytics.farm import CATEGORY_ACTIONS, CATEGORY_TITLES, TRUST_TITLES
from agropulse.schemas.analysis import FieldSummary

if TYPE_CHECKING:
    from agropulse.analytics.farm import FarmAssessment
    from agropulse.services.analysis import FarmSummaryView, RegistryRowView, RegistryView


def _clean(value: str) -> str:
    """Схлопнуть пробелы и запретить пустое название.

    Отдельная функция, а не `min_length`: строка из одних пробелов проходит
    проверку длины и попадает в реестр строкой-невидимкой, по которой
    хозяйство не найти.
    """
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("название хозяйства не может быть пустым")
    return cleaned


class FarmCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # Реквизиты необязательны все до единого: в промышленном внедрении они
    # приезжают из ведомственного реестра, а требовать ИНН у того, кто просто
    # смотрит на свою землю, значит закрыть перед ним сервис.
    inn: str | None = Field(default=None, max_length=12)
    legal_form: str | None = Field(default=None, max_length=50)
    district: str | None = Field(default=None, max_length=200)
    region: str | None = Field(default=None, max_length=200)
    contact: str | None = Field(default=None, max_length=200)
    note: str | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _clean(value)


class FarmUpdate(BaseModel):
    """Частичное обновление: `None` означает «не менять».

    Пустая строка в реквизите значит «стереть» — ИНН могли ввести ошибочно.
    С названием так нельзя: оно обязательно, и проверка это ловит.
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    inn: str | None = Field(default=None, max_length=12)
    legal_form: str | None = Field(default=None, max_length=50)
    district: str | None = Field(default=None, max_length=200)
    region: str | None = Field(default=None, max_length=200)
    contact: str | None = Field(default=None, max_length=200)
    note: str | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str | None) -> str | None:
        return None if value is None else _clean(value)


class FarmRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    inn: str | None
    legal_form: str | None
    district: str | None
    region: str | None
    contact: str | None
    note: str | None
    created_at: datetime


class FarmAssessmentRead(BaseModel):
    """Индекс потребности в поддержке с раскрытием того, из чего он сложился."""

    support_need_score: float | None
    trust: str
    trust_title: str
    category: str
    category_title: str
    action: str

    fields_total: int
    critical: int
    attention: int
    normal: int
    insufficient_data: int
    pending: int

    total_area_ha: float
    assessed_area_ha: float
    # Площадь, по которой заключения нет. Показывается отдельно и намеренно:
    # без неё низкий балл неотличим от отсутствия наблюдений.
    unassessed_area_ha: float
    problem_area_ha: float
    critical_area_ha: float

    assessed_share: float
    problem_share: float
    critical_share: float

    weighted_risk: float | None
    max_field_risk: float | None
    mean_confidence: float | None

    anomalies_total: int
    anomalies_confirmed: int

    reason: str | None
    notes: list[str]

    @classmethod
    def from_assessment(cls, assessment: "FarmAssessment") -> "FarmAssessmentRead":
        category = assessment.category.value
        trust = assessment.trust.value
        return cls(
            support_need_score=assessment.support_need_score,
            trust=trust,
            trust_title=TRUST_TITLES[trust],
            category=category,
            category_title=CATEGORY_TITLES[category],
            action=CATEGORY_ACTIONS[category],
            fields_total=assessment.fields_total,
            critical=assessment.critical,
            attention=assessment.attention,
            normal=assessment.normal,
            insufficient_data=assessment.insufficient_data,
            pending=assessment.pending,
            total_area_ha=assessment.total_area_ha,
            assessed_area_ha=assessment.assessed_area_ha,
            unassessed_area_ha=assessment.unassessed_area_ha,
            problem_area_ha=assessment.problem_area_ha,
            critical_area_ha=assessment.critical_area_ha,
            assessed_share=assessment.assessed_share,
            problem_share=assessment.problem_share,
            critical_share=assessment.critical_share,
            weighted_risk=assessment.weighted_risk,
            max_field_risk=assessment.max_field_risk,
            mean_confidence=assessment.mean_confidence,
            anomalies_total=assessment.anomalies_total,
            anomalies_confirmed=assessment.anomalies_confirmed,
            reason=assessment.reason,
            notes=assessment.notes,
        )


class FarmSummaryRead(BaseModel):
    farm: FarmRead
    period_from: date
    period_to: date
    assessment: FarmAssessmentRead
    fields: list[FieldSummary]

    @classmethod
    def from_view(cls, view: "FarmSummaryView") -> "FarmSummaryRead":
        return cls(
            farm=FarmRead.model_validate(view.farm),
            period_from=view.period_from,
            period_to=view.period_to,
            assessment=FarmAssessmentRead.from_assessment(view.assessment),
            fields=[FieldSummary.model_validate(item) for item in view.fields],
        )


class RegistryRow(BaseModel):
    """Строка реестра. `rank` пуст у хозяйства без заключения."""

    rank: int | None
    farm: FarmRead
    assessment: FarmAssessmentRead

    @classmethod
    def from_view(cls, view: "RegistryRowView") -> "RegistryRow":
        return cls(
            rank=view.rank,
            farm=FarmRead.model_validate(view.farm),
            assessment=FarmAssessmentRead.from_assessment(view.assessment),
        )


class RegistryRead(BaseModel):
    """Реестр приоритетной государственной поддержки.

    Списки разделены, а не слиты сортировкой. Хозяйство без заключения
    не ставится в конец очереди: последнее место читается как «поддержка
    не нужна», а сказать про него нечего. Поля без хозяйства не попадают
    в реестр вовсе, и этот факт виден, а не спрятан. Справочник хозяйств
    общий, поэтому те из них, у кого в этом проекте полей нет, перечислены
    отдельно — заведённое хозяйство не должно выглядеть пропавшим.
    """

    project_id: uuid.UUID
    period_from: date
    period_to: date
    farms_total: int
    total_area_ha: float
    rows: list[RegistryRow]
    undetermined: list[RegistryRow]
    # Хозяйства справочника, у которых в этом проекте полей нет.
    other_farms: list[FarmRead]
    unassigned_fields: list[FieldSummary]

    @classmethod
    def from_view(cls, view: "RegistryView") -> "RegistryRead":
        return cls(
            project_id=view.project_id,
            period_from=view.period_from,
            period_to=view.period_to,
            farms_total=view.farms_total,
            total_area_ha=view.total_area_ha,
            rows=[RegistryRow.from_view(row) for row in view.rows],
            undetermined=[RegistryRow.from_view(row) for row in view.undetermined],
            other_farms=[FarmRead.model_validate(farm) for farm in view.other_farms],
            unassigned_fields=[
                FieldSummary.model_validate(item) for item in view.unassigned_fields
            ],
        )
