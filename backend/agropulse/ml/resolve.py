"""Выбор реализации клиента моделей.

Штатный путь — локальная модель V6: она обучена заранее, её артефакты лежат
в образе рядом с кодом, и в сервисе выполняется только предсказание.

Если V6 отключена настройкой, остаётся обращение к внешнему сервису моделей
по контракту `docs/ML_API.md`.

Временно, пока нет ни того ни другого, допускается заглушка из `ml/baseline.py`.
Это костыль периода разработки, а не механизм отказоустойчивости: после
подключения модели ветка с заглушкой, настройка `ml_use_dev_stub` и сам модуль
заглушки удаляются.

Подмена никогда не выполняется молча — источник значения доезжает
до пользователя вместе с данными, чтобы было видно, чем восстановлен ряд.
"""

from __future__ import annotations

import logging

from agropulse.config import get_settings
from agropulse.errors import UpstreamError
from agropulse.ml.client import MLClient
from agropulse.ml.http_client import HttpMLClient
from agropulse.ml.v6_client import V6MLClient

logger = logging.getLogger(__name__)


class MLServiceUnavailable(UpstreamError):
    """Модель недоступна, а заглушка запрещена настройкой.

    Наследуется от ошибки внешней системы: недоступность сервиса моделей
    временна по своей природе, и задача обязана быть повторена, а не
    завершиться окончательной неудачей.
    """

    code = "ml_service_unavailable"
    message = "сервис моделей недоступен"


def get_client() -> MLClient:
    """Клиент моделей, пригодный к работе прямо сейчас."""
    settings = get_settings()

    if settings.ml_v6_enabled:
        local = V6MLClient(
            artifacts_dir=settings.ml_v6_artifacts_dir,
            reference_dataset=settings.ml_v6_reference_dataset,
        )
        if local.is_available():
            return local
        logger.error(
            "ml_v6_artifacts_missing",
            extra={
                "reason": "модель V6 включена, но её артефакты не найдены",
                "artifacts_dir": str(settings.ml_v6_artifacts_dir),
            },
        )

    service = HttpMLClient()
    if service.is_available():
        return service

    if not settings.ml_use_dev_stub:
        raise MLServiceUnavailable(
            f"модель V6 недоступна, сервис моделей не отвечает по адресу "
            f"{settings.ml_service_url}",
            ml_service_url=settings.ml_service_url,
        )

    # ВРЕМЕННО: убрать вместе с модулем заглушки после подключения модели.
    from agropulse.ml.baseline import BaselineMLClient

    logger.warning(
        "ml_dev_stub_used",
        extra={
            "reason": "модель недоступна, ряд восстанавливается "
            "приближением по соседним точкам",
            "ml_service_url": settings.ml_service_url,
        },
    )
    return BaselineMLClient()
