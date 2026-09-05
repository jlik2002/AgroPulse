"""Преобразование ошибок в HTTP-ответ.

Единственное место, где ошибка превращается во внешний ответ, и единственное,
где она пишется в лог. Логировать одно исключение в репозитории, сервисе,
роутере и middleware одновременно — значит получить четыре записи об одном
событии и ни одной с полным контекстом.

Формат ответа расширяет прежний, а не заменяет его: поле `detail` остаётся
на месте для клиентов, написанных до рефакторинга, а новое поле `error`
несёт стабильный код и `request_id` для поиска в логах.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from agropulse.errors import AppError
from agropulse.observability import get_request_id

logger = logging.getLogger(__name__)


def _response(status_code: int, code: str, message: object, detail: object) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(
            {
                "detail": detail,
                "error": {
                    "code": code,
                    "message": message,
                    "request_id": get_request_id(),
                },
            }
        ),
    )


async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    """Ожидаемая ошибка предметной области.

    Пишется как предупреждение без traceback: «поле не найдено» — штатный
    ответ сервиса, а не инцидент, и стек вызовов здесь ничего не добавляет.
    """
    logger.warning(
        exc.code,
        extra={"path": request.url.path, "error_code": exc.code, **exc.context},
    )
    return _response(exc.http_status, exc.code, exc.message, exc.message)


async def handle_http_exception(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Ошибки самого фреймворка: неизвестный маршрут, неподходящий метод."""
    code = "http_error" if exc.status_code >= 500 else f"http_{exc.status_code}"
    return _response(exc.status_code, code, exc.detail, exc.detail)


async def handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Запрос не прошёл проверку схемой.

    Список ошибок остаётся в `detail` в том же виде, в каком его отдавал
    FastAPI: на него могут опираться формы фронтенда.
    """
    return _response(422, "request_validation_error", "запрос не прошёл проверку", exc.errors())


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Всё остальное.

    Наружу уходит только код ошибки и идентификатор запроса. Подробности
    остаются в логах: текст исключения может содержать фрагменты запроса
    к базе или адреса внутренних сервисов.
    """
    logger.exception(
        "unhandled_error",
        extra={"path": request.url.path, "error_code": "internal_error"},
    )
    return _response(
        500, "internal_error", "внутренняя ошибка сервиса", "внутренняя ошибка сервиса"
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(Exception, handle_unexpected_error)
