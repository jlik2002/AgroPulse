"""Интерфейс к сервису ML-моделей.

Модели восстановления пропусков и прогноза живут в отдельном сервисе, который
разрабатывается независимо. Здесь описан только контракт; конкретный транспорт
скрыт за реализацией, поэтому переход с REST на брокер сообщений не затронет
пайплайн. Контракт зафиксирован в `docs/ML_API.md`.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from datetime import date
from typing import Protocol, runtime_checkable


@dataclass(slots=True)
class SeriesPoint:
    date: date
    primary_ndvi: float | None
    features: dict[str, float | None] = dataclass_field(default_factory=dict)


@dataclass(slots=True)
class ImputeRequest:
    polygon_id: str
    observations: list[SeriesPoint]
    targets: list[date]
    crop_type: str | None = None


@dataclass(slots=True)
class Prediction:
    date: date
    value: float
    confidence: float | None = None


@dataclass(slots=True)
class ImputeResult:
    predictions: list[Prediction]
    model_version: str
    source: str  # какая реализация ответила: внешний сервис или локальный baseline


@runtime_checkable
class MLClient(Protocol):
    """Клиент моделей."""

    name: str

    def is_available(self) -> bool: ...

    def impute(self, request: ImputeRequest) -> ImputeResult:
        """Восстановить значения `primary_ndvi` на запрошенные даты."""
        ...
