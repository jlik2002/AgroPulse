FROM python:3.12-slim AS base

# Системные библиотеки:
#   libpango/libcairo/libgdk-pixbuf — нужны WeasyPrint для генерации PDF-отчётов;
#   libexpat/shared-mime-info       — его же зависимости;
#   curl                            — диагностика внутри контейнера.
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
COPY pyproject.toml /app/pyproject.toml
COPY backend/agropulse/__init__.py /app/backend/agropulse/__init__.py
RUN pip install --upgrade pip && pip install /app

COPY backend /app/backend
COPY scripts /app/scripts

# Запуск от непривилегированного пользователя: в кластере под поднимается
# с runAsNonRoot, и образ должен это поддерживать.
RUN useradd --create-home --uid 10001 agropulse && chown -R agropulse:agropulse /app
USER agropulse

ENV PYTHONPATH=/app/backend
WORKDIR /app/backend

EXPOSE 8000
CMD ["uvicorn", "agropulse.main:app", "--host", "0.0.0.0", "--port", "8000"]
