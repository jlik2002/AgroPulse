"""Выбор реализации клиента моделей.

Штатный путь один: обращение к внешнему сервису ML-моделей.

Временно, пока сервис не готов, при недоступности допускается заглушка
из `ml/baseline.py`. Это костыль периода разработки, а не механизм
отказоустойчивости: после подключения сервиса ветка с заглушкой, настройка
`ml_use_dev_stub` и сам модуль заглушки удаляются.

Подмена никогда не выполняется молча — источник значения доезжает
до пользователя вместе с данными, чтобы было видно, чем восстановлен ряд.
"""

from __future__ import annotations

import logging

from agropulse.config import get_settings
from agropulse.errors import UpstreamError
from agropulse.ml.client import MLClient
from agropulse.ml.http_client import HttpMLClient

logger = logging.getLogger(__name__)


class MLServiceUnavailable(UpstreamError):
    """Сервис моделей недоступен, а заглушка запрещена настройкой.

    Наследуется от ошибки внешней системы: недоступность сервиса моделей
    временна по своей природе, и задача обязана быть повторена, а не
    завершиться окончательной неудачей.
    """

    code = "ml_service_unavailable"
    message = "сервис моделей недоступен"


def get_client() -> MLClient:
    """Клиент моделей, пригодный к работе прямо сейчас."""
    service = HttpMLClient()
    if service.is_available():
        return service

    settings = get_settings()
    if not settings.ml_use_dev_stub:
        raise MLServiceUnavailable(
            f"сервис моделей недоступен по адресу {settings.ml_service_url}",
            ml_service_url=settings.ml_service_url,
        )

    # ВРЕМЕННО: убрать вместе с модулем заглушки после подключения сервиса.
    from agropulse.ml.baseline import BaselineMLClient

    logger.warning(
        "ml_dev_stub_used",
        extra={
            "reason": "сервис моделей недоступен, ряд восстанавливается "
            "приближением по соседним точкам",
            "ml_service_url": settings.ml_service_url,
        },
    )
    return BaselineMLClient()
