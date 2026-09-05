FROM python:3.12-slim AS base

# Системные библиотеки:
#   libpango/libcairo/libgdk-pixbuf — нужны WeasyPrint для генерации PDF-отчётов;
#   libexpat/shared-mime-info       — его же зависимости;
#   curl                            — проба живости контейнера в compose.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        shared-mime-info \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Зависимости ставим отдельным слоем: правки кода не вызывают их переустановку.
# Пакет ставится по одному лишь `__init__.py`, а рабочий код приезжает ниже
# и находится через PYTHONPATH — так слой зависимостей не инвалидируется.
COPY pyproject.toml /app/pyproject.toml
COPY backend/agropulse/__init__.py /app/backend/agropulse/__init__.py

# Инструменты разработки (pytest, ruff) не попадают в образ, предназначенный
# для эксплуатации. Локальный compose собирает образ с INSTALL_DEV=true,
# чтобы `docker compose run --rm api pytest` работал без отдельного образа.
ARG INSTALL_DEV=false
RUN pip install --upgrade pip \
    && if [ "$INSTALL_DEV" = "true" ]; then pip install "/app[dev]"; else pip install /app; fi

COPY backend /app/backend
COPY scripts /app/scripts

# Запуск от непривилегированного пользователя: в кластере под поднимается
# с runAsNonRoot, и образ должен это поддерживать.
RUN useradd --create-home --uid 10001 agropulse && chown -R agropulse:agropulse /app
USER agropulse

ENV PYTHONPATH=/app/backend
WORKDIR /app/backend

EXPOSE 8000

# Exec-форма и фабрика приложения: uvicorn получает SIGTERM напрямую, а
# приложение собирается вызовом функции, а не на импорте модуля.
CMD ["uvicorn", "agropulse.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
