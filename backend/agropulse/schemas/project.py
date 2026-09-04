"""Схемы проекта — анонимного рабочего пространства пользователя."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProjectCreate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    period_from: date
    period_to: date

    @model_validator(mode="after")
    def check_period(self) -> "ProjectCreate":
        if self.period_to < self.period_from:
            raise ValueError("конец периода раньше начала")
        # Период анализа общий для всех полей проекта, чтобы результаты
        # были сопоставимы при ранжировании.
        if (self.period_to - self.period_from).days < 14:
            raise ValueError("период короче 14 дней: временной ряд будет непоказательным")
        return self


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str | None
    period_from: date
    period_to: date
    created_at: datetime
