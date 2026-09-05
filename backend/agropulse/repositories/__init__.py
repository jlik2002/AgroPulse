"""Доступ к PostgreSQL.

Весь SQL сервиса живёт здесь. Репозиторий выражает бизнес-запрос
(«ряд поля по типам значений», «аномалии нескольких полей одним запросом»),
а не оборачивает таблицу набором `get/create/update/delete`: универсальный
базовый репозиторий на практике только прячет SQL, не убирая его.

Репозиторий не решает, когда завершать транзакцию. Ему разрешены `add`,
`flush`, `execute`, `delete`; `commit` и `rollback` вызывает слой выше —
сервис, которому известна граница бизнес-операции.
"""

from agropulse.repositories.anomalies import AnomalyRepository
from agropulse.repositories.farms import FarmRepository
from agropulse.repositories.fields import FieldRepository
from agropulse.repositories.forecasts import ForecastRepository
from agropulse.repositories.jobs import JobRepository
from agropulse.repositories.observations import ObservationRepository
from agropulse.repositories.projects import ProjectRepository
from agropulse.repositories.radar import RadarObservationRepository
from agropulse.repositories.raw_cache import RawCacheRepository
from agropulse.repositories.reports import GeneratedReportRepository

__all__ = [
    "AnomalyRepository",
    "FarmRepository",
    "FieldRepository",
    "ForecastRepository",
    "GeneratedReportRepository",
    "JobRepository",
    "ObservationRepository",
    "ProjectRepository",
    "RadarObservationRepository",
    "RawCacheRepository",
]
