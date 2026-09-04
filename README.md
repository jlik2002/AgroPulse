# AgroPulse

Веб-сервис дистанционного мониторинга сельскохозяйственных полей.

Пользователь находит регион на карте, выбирает готовый сельскохозяйственный контур
или рисует полигон вручную. Дальше сервис самостоятельно получает спутниковые
(Sentinel-2) и метеорологические данные, строит временной ряд NDVI, восстанавливает
пропущенные наблюдения, находит негативные аномальные периоды и прогнозирует риск
ухудшения на 14 дней. Результат — интерактивная аналитика, выгрузка CSV и
человекочитаемый PDF-отчёт.

Ручная загрузка заранее подготовленного датасета в основном сценарии не требуется.

> **Статус разработки.** Готов этап E0 — каркас сервиса и инфраструктура.
> План работ и границы этапов: [`docs/PLAN.md`](docs/PLAN.md).

## Стек

| Слой | Технологии |
|---|---|
| Бэкенд | FastAPI, Pydantic v2, SQLAlchemy 2, Alembic |
| Очередь задач | Celery + Redis, две очереди: `collect` и `analyze` |
| Хранение | PostgreSQL 16 + PostGIS, MinIO (S3-совместимое) |
| Спутниковые данные | Google Earth Engine (Sentinel-2), STAC как резервный источник |
| Погода | Open-Meteo (архив ERA5 и прогноз на 14 дней) |
| Контуры полей | OpenStreetMap / Overpass API, ESA WorldCereal |
| LLM | OpenRouter — только пересказ проверенных расчётов |
| Окружение | Docker Compose; Helm-чарт для Kubernetes |

## Быстрый старт

Нужен Docker с плагином Compose. Больше ничего ставить не требуется.

```bash
cp .env.example .env
docker compose up -d --build
```

Сервис поднимется на <http://localhost:8000>. Проверка:

```bash
curl http://localhost:8000/health/ready
# {"status":"ok","checks":{"postgres":true,"s3":true}}
```

Документация API — <http://localhost:8000/docs>.
Веб-консоль MinIO — <http://localhost:9001> (логин и пароль из `.env`).

Остановить и удалить данные:

```bash
docker compose down -v
```

### Доступ к Google Earth Engine

Сервис поднимается и без ключа GEE — сбор спутниковых данных в этом случае
переключается на резервный источник STAC. Чтобы задействовать основной канал:

1. Создайте проект в [Google Cloud Console](https://console.cloud.google.com) и запомните его **Project ID**.
2. Зарегистрируйте проект в Earth Engine: <https://console.cloud.google.com/earth-engine>
   (для учебных и исследовательских задач — бесплатный noncommercial-тариф).
3. Включите Earth Engine API:
   <https://console.cloud.google.com/apis/library/earthengine.googleapis.com>
4. Создайте сервис-аккаунт: <https://console.cloud.google.com/iam-admin/serviceaccounts/create>
   и выдайте ему роли **Earth Engine Resource Viewer** и **Service Usage Consumer**.
5. Выпустите для него ключ формата JSON (*Manage keys → Add key → Create new key → JSON*)
   и сохраните файл как `secrets/gee-service-account.json`.
6. Пропишите `GEE_PROJECT=<ваш Project ID>` в `.env`.

Проверить всю цепочку — от чтения ключа до расчёта NDVI по тестовому полигону:

```bash
docker compose run --rm api python /app/scripts/check_gee.py
```

Скрипт проходит пять шагов и на каждом сообщает, что именно не так. Успешное
завершение означает, что доступ настроен полностью.

Подробнее — [`secrets/README.md`](secrets/README.md). Каталог `secrets/` в репозиторий не попадает.

## Структура репозитория

```
backend/
  agropulse/
    main.py            точка входа FastAPI
    config.py          настройки, читаются только из переменных окружения
    db/                модели SQLAlchemy и подключение к базе
    api/routers/       HTTP-эндпоинты
    providers/         внешние источники данных за общими интерфейсами
    features/          построение признаков для ML-сервиса
    ml/                клиент ML-сервиса и локальный baseline
    analytics/         климатология, аномалии, составной риск
    llm/               генерация пояснений через OpenRouter
    reports/           выгрузка CSV и генерация PDF
    storage/           объектное хранилище артефактов
    tasks/             задачи Celery
    cli.py             batch-инференс
  migrations/          миграции Alembic
scripts/               служебные скрипты (проверка доступа к внешним API)
deploy/helm/           чарт для Kubernetes
docs/                  план работ, контракт с ML-сервисом, отчёт
data/demo/             демонстрационные данные и прогретый кэш
```

## Архитектура

```
api              FastAPI: REST и поток прогресса SSE, долгих операций не выполняет
worker-collect   Celery: обращения к GEE, STAC, Open-Meteo. Упирается в сеть
worker-analyze   Celery: климатология, аномалии, риск, отчёты. Упирается в CPU
postgres         PostGIS: полигоны полей, наблюдения, аномалии, прогнозы
redis            брокер Celery, кэш внешних API, шина прогресса
minio            PDF-отчёты, превью снимков, кэш растров
ml-service       внешний сервис моделей, подключается по REST
```

Миграции выполняет отдельный шаг (`migrate` в Compose, Job в Kubernetes), а не старт
приложения: иначе несколько реплик API пошли бы накатывать их наперегонки.

Модели восстановления пропусков и прогноза живут во внешнем сервисе. Контракт
обмена описан в [`docs/ML_API.md`](docs/ML_API.md); при недоступности сервиса
пайплайн переключается на локальный baseline и помечает это в качестве данных.

## Разработка

Код смонтирован в контейнеры, uvicorn перезагружается автоматически.

```bash
docker compose logs -f api            # логи
docker compose restart worker-collect # перезапуск воркера после правок задач
```

Новая миграция после изменения моделей:

```bash
docker compose run --rm --user "$(id -u):$(id -g)" migrate \
  alembic revision --autogenerate -m "описание изменения"
docker compose run --rm migrate alembic upgrade head
```

## Лицензии и источники данных

Все внешние источники — открытые: Copernicus Sentinel-2, ERA5 через Open-Meteo,
OpenStreetMap (ODbL), ESA WorldCereal. Перечень используемых коллекций и параметров
предобработки фиксируется в [`docs/RESEARCH.md`](docs/RESEARCH.md).
