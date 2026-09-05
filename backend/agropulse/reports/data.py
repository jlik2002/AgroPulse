"""Данные для выгрузок и отчётов.

Сборщики отчётов не обращаются к базе. Они получают уже прочитанные строки
и занимаются только представлением: вёрсткой, графиками, текстами. Причина
практическая — отчёт по полю и сводный отчёт читают одни и те же сущности,
и запрос внутри рендера означал бы N+1 при построении сводки по хозяйству.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date

from agropulse.analytics.farm import FarmAssessment
from agropulse.db.models import (
    Anomaly,
    Farm,
    Field,
    ForecastRun,
    Observation,
    RadarObservation,
)


@dataclass(slots=True)
class FieldData:
    """Полный набор данных одного поля за период проекта."""

    field: Field
    period_from: date
    period_to: date
    observations: list[Observation] = dataclass_field(default_factory=list)
    radar: list[RadarObservation] = dataclass_field(default_factory=list)
    anomalies: list[Anomaly] = dataclass_field(default_factory=list)
    forecast_run: ForecastRun | None = None

    @property
    def in_period(self) -> list[Observation]:
        return [o for o in self.observations if self.period_from <= o.date <= self.period_to]


@dataclass(slots=True)
class ProjectData:
    """Данные всех полей проекта."""

    project_id: object
    period_from: date
    period_to: date
    fields: list[FieldData] = dataclass_field(default_factory=list)


@dataclass(slots=True)
class FarmData:
    """Данные хозяйства для заключения.

    Индекс приходит уже посчитанным. Сборщик отчёта не считает ничего:
    иначе цифра в PDF и цифра на экране разошлись бы при первой же правке
    формулы, а объяснить комиссии, какая из них верная, было бы нечем.
    """

    farm: Farm
    period_from: date
    period_to: date
    assessment: FarmAssessment
    fields: list[FieldData] = dataclass_field(default_factory=list)


@dataclass(slots=True)
class RegistryEntry:
    farm: Farm
    assessment: FarmAssessment
    rank: int | None = None


@dataclass(slots=True)
class RegistryData:
    """Реестр приоритетной поддержки: ранжированные хозяйства и остаток.

    Поля без хозяйства перечисляются отдельно и полным списком. Молча
    выбросить их из реестра нельзя: это площадь, которую документ
    не покрывает, и распорядитель средств обязан об этом знать.
    """

    project_id: object
    period_from: date
    period_to: date
    rows: list[RegistryEntry] = dataclass_field(default_factory=list)
    undetermined: list[RegistryEntry] = dataclass_field(default_factory=list)
    unassigned_fields: list[Field] = dataclass_field(default_factory=list)
