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
from agropulse.ml.http_client import HttpMLClient

logger = logging.getLogger(__name__)


class MLServiceUnavailable(RuntimeError):
    """Сервис моделей недоступен, а заглушка запрещена настройкой."""


def get_client():
    """Клиент моделей, пригодный к работе прямо сейчас."""
    service = HttpMLClient()
    if service.is_available():
        return service

    settings = get_settings()
    if not settings.ml_use_dev_stub:
        raise MLServiceUnavailable(
            f"сервис моделей недоступен по адресу {settings.ml_service_url}"
        )

    # ВРЕМЕННО: убрать вместе с модулем заглушки после подключения сервиса.
    from agropulse.ml.baseline import BaselineMLClient

    logger.warning(
        "Сервис моделей недоступен, используется ВРЕМЕННАЯ ЗАГЛУШКА "
        "(приближение по соседним точкам). Это режим разработки."
    )
    return BaselineMLClient()
