# AgroPulse

Веб-сервис дистанционного мониторинга сельскохозяйственных полей.

Пользователь находит регион на карте, выбирает готовый сельскохозяйственный контур
или рисует полигон вручную. Дальше сервис самостоятельно получает спутниковые
(Sentinel-2) и метеорологические данные, строит временной ряд NDVI, восстанавливает
пропущенные наблюдения, находит негативные аномальные периоды и прогнозирует риск
ухудшения на 14 дней. Результат — интерактивная аналитика, выгрузка CSV и
человекочитаемый PDF-отчёт.

Ручная загрузка заранее подготовленного датасета в основном сценарии не требуется.

> **Статус разработки.** Готовы этапы E0–E7: инфраструктура, управление полями,
> автоматический сбор спутниковых и погодных данных, поиск региона и готовых
> контуров, восстановление пропусков, детекция аномалий, составной риск,
> прогноз на 14 суток, batch-инференс, выгрузка CSV, PDF-отчёты и веб-интерфейс.
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
| LLM | OpenRouter — только пересказ проверенных расчётов, со сверкой чисел |
| Отчёты | WeasyPrint и Jinja2 для PDF, matplotlib для графиков |
| Фронтенд | React 18, TypeScript, Vite, Tailwind CSS, Radix UI |
| Карта и графики | Leaflet и leaflet-geoman, подложки CARTO и Esri, ECharts |
| Окружение | Docker Compose; Helm-чарт для Kubernetes |

## Быстрый старт

Нужен Docker с плагином Compose. Больше ничего ставить не требуется.

```bash
cp .env.example .env
docker compose up -d --build
```

Веб-интерфейс откроется на <http://localhost:5173>, API — на <http://localhost:8000>.
Проверка:

```bash
curl http://localhost:8000/health/ready
# {"status":"ok","checks":{"postgres":true,"s3":true}}
```

Документация API — <http://localhost:8000/docs>.
Веб-консоль MinIO — <http://localhost:9001> (логин и пароль из `.env`).

Адрес бэкенда в сборку фронтенда не зашит: путь `/api` проксирует nginx внутри
контейнера `web`. Поэтому один и тот же образ работает и в Compose, и в Kubernetes.

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

## Пользовательский сценарий в интерфейсе

Порядок экранов повторяет рабочий цикл агронома:

1. **Поля** — поиск региона или ввод координат, готовые контуры пашни из
   OpenStreetMap либо ручное рисование полигона, период анализа.
2. **Проверка параметров** — состав полей, площадь, источники данных и
   предупреждения. Не указанная культура запуск не блокирует.
3. **Обработка** — прогресс по пяти шагам для каждого поля отдельно, поток
   событий через SSE. Готовое поле открывается, не дожидаясь остальных.
4. **Сводка** — счётчики статусов, карта с окрашенными контурами и очередь
   на осмотр, ранжированная по составному риску.
5. **Поле** — вкладки «Обзор», «Снимки», «Динамика» и «Данные»: вывод и
   рекомендуемое действие, затем доказательства, затем подробные значения.
6. **Прогноз** — линия на 14 дней с коридором вероятных значений, факторы
   влияния и прямо названные ограничения метода.
7. **Отчёты** — выбор разделов, живой предпросмотр и скачивание PDF.

Главный принцип интерфейса: сначала решение, затем доказательства, после
этого подробные данные и отчёт. Цвет статуса всегда сопровождается текстом,
а происхождение каждого значения — наблюдение, восстановление или прогноз —
показывается отдельно и не смешивается.

## Пользовательский сценарий через API

```bash
API=http://localhost:8000/api

# 1. Проект с общим периодом анализа
PID=$(curl -s -X POST $API/projects -H 'Content-Type: application/json' \
  -d '{"name":"Демо","period_from":"2023-04-01","period_to":"2023-10-01"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

# 2. Поле: полигон GeoJSON, культура и дата посева необязательны
FID=$(curl -s -X POST $API/projects/$PID/fields -H 'Content-Type: application/json' -d '{
  "name":"Поле 1","crop":"кукуруза","sowing_date":"2023-04-25",
  "geometry":{"type":"Polygon","coordinates":[[[-93.60,41.98],[-93.59,41.98],
    [-93.59,41.988],[-93.60,41.988],[-93.60,41.98]]]}}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

# 3. Обработка — выполняется воркером, ответ приходит сразу
curl -s -X POST $API/projects/$PID/process

# 4. Ход обработки по девяти стадиям (поток SSE)
curl -sN $API/projects/$PID/events

# 5. Результаты
curl -s $API/fields/$FID/timeseries   # ряд со сводкой качества данных
curl -s $API/fields/$FID/anomalies    # аномальные периоды и гипотезы о причинах
curl -s $API/fields/$FID/risk         # составной риск с вкладом факторов
curl -s $API/projects/$PID/summary    # сводка и очередь на осмотр

# 6. Выгрузка
curl -s $API/fields/$FID/export.csv   -o field.csv
curl -s $API/fields/$FID/report.pdf   -o field.pdf     # отчёт по полю
curl -s $API/projects/$PID/report.pdf -o summary.pdf   # сводный отчёт
```

### Batch-инференс

Вторая точка запуска: восстановление скрытых значений по готовому файлу.

```bash
cp private_features.csv data/
docker compose run --rm --user "$(id -u):$(id -g)" api \
  python -m agropulse.cli predict \
    --input /app/data/private_features.csv \
    --output /app/data/submission.csv

# проверка формата перед загрузкой на платформу
docker compose run --rm --user "$(id -u):$(id -g)" api \
  python -m agropulse.cli validate \
    --input /app/data/private_features.csv \
    --submission /app/data/submission.csv
```

Поиск территории без ручного ввода координат:

```bash
curl -s "$API/regions/search?q=Тимашевский+район"          # регион по названию
curl -s -X POST $API/parcels/search -H 'Content-Type: application/json' \
  -d '{"west":38.7,"south":45.5,"east":38.9,"north":45.7}'  # контуры пашни из OSM
```

Площадь поля считается геодезически при добавлении. Полигон проверяется на
самопересечения и разумность размера — ответ 422 с понятным текстом.

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
frontend/
  src/
    api/               клиент REST и подписка на поток прогресса
    app/               оболочка проекта и общий контекст
    components/        карта, графики, интерфейсные примитивы
    pages/             экраны пользовательского сценария
    lib/               форматирование, статусы, разбор временного ряда
  nginx.conf.template  раздача SPA и проксирование /api
scripts/               служебные скрипты (проверка доступа к внешним API)
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
web              nginx: раздача React-приложения и проксирование /api
ml-service       внешний сервис моделей, подключается по REST
```

Миграции выполняет отдельный шаг (`migrate` в Compose, Job в Kubernetes), а не старт
приложения: иначе несколько реплик API пошли бы накатывать их наперегонки.

Модели восстановления пропусков и прогноза живут во внешнем сервисе. Контракт
обмена описан в [`docs/ML_API.md`](docs/ML_API.md); пока сервис не готов,
настройка `ML_USE_DEV_STUB` разрешает временную заглушку, и источник значения
доезжает до пользователя вместе с данными.

## Разработка

Код смонтирован в контейнеры, uvicorn перезагружается автоматически.

```bash
docker compose logs -f api            # логи
docker compose restart worker-collect # перезапуск воркера после правок задач
docker compose run --rm api pytest    # тесты
docker compose run --rm api ruff check .
```

Фронтенд удобнее разрабатывать вне контейнера: Vite отдаёт горячую перезагрузку,
а запросы к `/api` проксирует на поднятый Compose'ом бэкенд.

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
npm run typecheck  # проверка типов
npm run build      # сборка, та же, что и в образе web
```

Адрес бэкенда для прокси задаётся переменной `VITE_API_PROXY`
(по умолчанию `http://localhost:8000`).

Локальный образ собирается с `INSTALL_DEV=true` и несёт pytest и ruff;
образ для эксплуатации остаётся без инструментов разработки.

Интеграционные тесты создают отдельную базу `${POSTGRES_DB}_test`, накатывают
на неё миграции и удаляют её после прогона. Тем самым проверяется и то, что
миграции применяются на пустой базе. Если PostgreSQL недоступен, эти тесты
пропускаются, а модульные продолжают работать.

Устройство слоёв, карта сервиса и принятые при рефакторинге решения —
в [`docs/REFACTORING.md`](docs/REFACTORING.md).

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
