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

from agropulse.db.models import (
    Anomaly,
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
