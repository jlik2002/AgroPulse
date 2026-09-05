"""Ошибки предметной области.

Бизнес-код не знает про HTTP и не возбуждает `HTTPException`: одна и та же
операция вызывается и из роутера, и из Celery-задачи, и из CLI, а код ответа
имеет смысл только в первом случае. Преобразование в HTTP выполняет
обработчик в `agropulse/api/errors.py`.

У каждой ошибки есть стабильный код. Он уходит клиенту и попадает в логи,
поэтому по нему можно искать инцидент, не разбирая текст сообщения.
Сообщение предназначено человеку и может меняться; код — нет.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Базовая ошибка сервиса.

    `http_status` объявлен здесь, а не в слое API, чтобы не заводить отдельную
    таблицу соответствий, которую придётся синхронизировать при каждой новой
    ошибке. Значение читает обработчик; сам бизнес-код им не пользуется.
    """

    code: str = "internal_error"
    http_status: int = 500
    message: str = "внутренняя ошибка сервиса"

    def __init__(self, message: str | None = None, **context: Any) -> None:
        self.message = message or self.message
        # Контекст уходит в логи как отдельные поля, а не в текст сообщения:
        # так по нему можно фильтровать.
        self.context = context
        super().__init__(self.message)


# ----------------------------------------------------------------------
# Отсутствующие сущности
# ----------------------------------------------------------------------


class NotFoundError(AppError):
    code = "not_found"
    http_status = 404
    message = "объект не найден"


class ProjectNotFoundError(NotFoundError):
    code = "project_not_found"
    message = "проект не найден"


class FieldNotFoundError(NotFoundError):
    code = "field_not_found"
    message = "поле не найдено"


# ----------------------------------------------------------------------
# Некорректный запрос
# ----------------------------------------------------------------------


class ValidationError(AppError):
    code = "validation_error"
    http_status = 422
    message = "запрос не прошёл проверку"


class InvalidGeometryError(ValidationError):
    """Полигон непригоден для анализа. Текст показывается пользователю."""

    code = "invalid_geometry"
    message = "полигон непригоден для анализа"


class InvalidBoundingBoxError(ValidationError):
    code = "invalid_bounding_box"
    message = "некорректные границы прямоугольника"


class EmptyProjectError(AppError):
    code = "project_has_no_fields"
    http_status = 400
    message = "в проекте нет полей"


# ----------------------------------------------------------------------
# Внешние системы
# ----------------------------------------------------------------------


class UpstreamError(AppError):
    """Внешний источник не смог отдать данные."""

    code = "upstream_unavailable"
    http_status = 503
    message = "внешний источник данных недоступен"


# ----------------------------------------------------------------------
# Пайплайн обработки
# ----------------------------------------------------------------------


class PipelineError(AppError):
    """Обработка поля не удалась."""

    code = "pipeline_failed"
    http_status = 500
    message = "обработка поля не выполнена"


class TransientPipelineError(PipelineError):
    """Временная неудача: сеть, внешний источник, недоступный сервис моделей.

    Единственный класс ошибок, для которого Celery выполняет повтор. Повторять
    что-либо ещё означало бы повторять ошибки программирования и некорректные
    данные, а это лишь тратит воркеры и откладывает диагностику.
    """

    code = "pipeline_transient_failure"
    message = "временная ошибка обработки, задача будет повторена"


class InsufficientDataError(PipelineError):
    """Данных не хватило для расчёта. Повтор бессмысленен."""

    code = "insufficient_data"
    message = "источники не вернули данных за запрошенный период"
