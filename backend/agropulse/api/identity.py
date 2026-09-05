"""Анонимный идентификатор посетителя в cookie.

Регистрации в сервисе нет, но проект должен находиться при следующем заходе:
пользователь закрыл вкладку, вернулся через день и ожидает увидеть свою сводку
и отчёты, а не пустое рабочее пространство. Раньше указатель на проект лежал
в localStorage браузера и терялся при любой его чистке, в приватном окне и на
втором устройстве; вдобавок сервер о принадлежности проектов ничего не знал.

Теперь идентификатор выдаёт сервер и хранит его в cookie, а проекты пишутся
с ссылкой на владельца. Этого хватает, чтобы вернуть человека к его работе.

Чем это **не** является: механизмом разграничения доступа. Идентификатор
никем не подтверждён, и знание идентификатора проекта по-прежнему открывает
его кому угодно — так задумано, ссылкой на проект делятся. Поэтому cookie
решает ровно одну задачу — «показать мои проекты», и ни в одном месте
не выступает проверкой прав.

Middleware написан на голом ASGI по той же причине, что и `RequestContextMiddleware`:
`BaseHTTPMiddleware` мешает потоковой отдаче SSE.
"""

from __future__ import annotations

import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

COOKIE_NAME = "agropulse_uid"

# Год. Меньший срок означал бы, что пользователь теряет свои проекты между
# сезонами полевых работ — то есть ровно тогда, когда возвращается к сервису.
COOKIE_MAX_AGE_SECONDS = 365 * 24 * 60 * 60


class AnonymousIdentityMiddleware:
    """Выдаёт и читает идентификатор посетителя.

    Кука ставится только когда её не было или она испорчена: переписывать
    её на каждом ответе значило бы слать лишний заголовок в том числе
    в SSE-поток, живущий минутами.
    """

    def __init__(self, app: ASGIApp, *, secure: bool = False) -> None:
        self._app = app
        self._secure = secure

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        existing = _read_cookie(scope)
        owner_id = existing or uuid.uuid4()

        # `Request.state` читает этот же словарь, поэтому значение доступно
        # зависимостям обычным способом, без обращения к scope напрямую.
        scope.setdefault("state", {})["owner_id"] = owner_id

        if existing is not None:
            await self._app(scope, receive, send)
            return

        header = _cookie_header(owner_id, secure=self._secure)

        async def send_with_cookie(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).append("set-cookie", header)
            await send(message)

        await self._app(scope, receive, send_with_cookie)


def _read_cookie(scope: Scope) -> uuid.UUID | None:
    """Достать идентификатор из заголовка Cookie.

    Чужое или испорченное значение не ошибка: выдаём новое. Падать из-за
    того, что в браузере лежит мусор, сервис не должен.
    """
    raw = Headers(scope=scope).get("cookie")
    if not raw:
        return None

    for chunk in raw.split(";"):
        name, _, value = chunk.strip().partition("=")
        if name == COOKIE_NAME:
            try:
                return uuid.UUID(value)
            except ValueError:
                return None
    return None


def _cookie_header(owner_id: uuid.UUID, *, secure: bool) -> str:
    """Собрать значение Set-Cookie средствами Starlette, а не строкой.

    HttpOnly обязателен: значение нужно только серверу, и скрипту на странице
    его читать незачем. SameSite=Lax оставляет куку на переходах по ссылке
    на проект — ради этого сценария всё и делается.
    """
    carrier = Response()
    carrier.set_cookie(
        key=COOKIE_NAME,
        value=str(owner_id),
        max_age=COOKIE_MAX_AGE_SECONDS,
        path="/",
        httponly=True,
        samesite="lax",
        secure=secure,
    )
    return carrier.headers["set-cookie"]


def get_owner_id(request: Request) -> uuid.UUID:
    """Идентификатор текущего посетителя.

    Значение кладёт middleware, поэтому оно есть всегда. Запасной вариант
    оставлен на случай, когда приложение собрано без middleware — например
    в узком тесте: лучше выдать разовый идентификатор, чем упасть.
    """
    owner_id = getattr(request.state, "owner_id", None)
    return owner_id if isinstance(owner_id, uuid.UUID) else uuid.uuid4()
