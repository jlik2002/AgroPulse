"""Сквозной идентификатор запроса и запись о его завершении.

Middleware написан на голом ASGI, а не поверх `BaseHTTPMiddleware`, ради
SSE-эндпоинта: обёртка `BaseHTTPMiddleware` пропускает ответ через
дополнительную очередь и мешает потоковой отдаче событий.

Идентификатор берётся из заголовка `X-Request-ID`, если его проставил Ingress
или клиент, и создаётся здесь, если нет. Он возвращается в ответе и попадает
в каждую запись лога, поэтому по одному значению из ответа можно найти всё,
что происходило с запросом.
"""

from __future__ import annotations

import logging
import time

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agropulse.observability import new_request_id, request_context

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "x-request-id"


class RequestContextMiddleware:
    """Устанавливает контекст запроса и пишет запись о его завершении."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request_id = Headers(scope=scope).get(REQUEST_ID_HEADER) or new_request_id()
        started_at = time.perf_counter()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        with request_context(request_id):
            try:
                await self._app(scope, receive, send_with_request_id)
            finally:
                # Длительность нужна для поиска медленных ручек: без неё
                # «сервис тормозит» невозможно ни подтвердить, ни опровергнуть.
                logger.info(
                    "http_request_finished",
                    extra={
                        "method": scope.get("method"),
                        "path": scope.get("path"),
                        "status_code": status_code,
                        "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    },
                )
