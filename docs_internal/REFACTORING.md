# Рефакторинг сервиса: карта, решения, границы

Документ ведётся по гайду `legacy_service_refactoring_guide.md`. Первая часть —
инвентаризация (этап 0): что где находится и какие внешние контракты нельзя
ломать. Вторая — журнал принятых решений.

## 1. Точки входа

```text
FastAPI:
  agropulse/main.py:create_app          — фабрика приложения

Celery:
  agropulse/tasks/celery_app.py:celery_app
  задачи: agropulse/tasks/pipeline.py

PostgreSQL:
  agropulse/db/session.py:get_engine    — движок, один на процесс, создаётся лениво
  agropulse/db/uow.py:UnitOfWork        — граница транзакции и репозитории
  миграции: backend/migrations/

Redis:
  agropulse/redis_client.py             — единственный клиент кэша и шины
  брокер Celery конфигурируется отдельным URL (другая логическая база)

S3 / MinIO:
  agropulse/storage/s3.py

Команды:
  API:     uvicorn agropulse.main:create_app --factory --host 0.0.0.0 --port 8000
  Worker:  celery -A agropulse.tasks.celery_app.celery_app worker --queues collect
           celery -A agropulse.tasks.celery_app.celery_app worker --queues analyze
  Миграции: alembic upgrade head
  Batch:   python -m agropulse.cli predict --input ... --output ...
  Тесты:   pytest
```

Celery Beat не используется: периодических задач в сервисе нет.

## 2. HTTP-эндпоинты

Префикс `/api` (настройка `API_PREFIX`), пробы живут вне префикса.

| Метод | Путь | Код успеха |
|---|---|---|
| GET | `/health/live` | 200 |
| GET | `/health/ready` | 200 / 503 |
| POST | `/api/projects` | 201 |
| GET | `/api/projects/{project_id}` | 200 |
| DELETE | `/api/projects/{project_id}` | 204 |
| POST | `/api/projects/{project_id}/fields` | 201 |
| GET | `/api/projects/{project_id}/fields` | 200 |
| GET | `/api/fields/{field_id}` | 200 |
| PATCH | `/api/fields/{field_id}` | 200 |
| DELETE | `/api/fields/{field_id}` | 204 |
| GET | `/api/fields/{field_id}/timeseries` | 200 |
| POST | `/api/fields/{field_id}/process` | 202 |
| POST | `/api/projects/{project_id}/process` | 202 |
| GET | `/api/regions/search` | 200 |
| POST | `/api/parcels/search` | 200 |
| GET | `/api/fields/{field_id}/anomalies` | 200 |
| GET | `/api/fields/{field_id}/risk` | 200 |
| GET | `/api/projects/{project_id}/summary` | 200 |
| GET | `/api/projects/{project_id}/events` | 200, `text/event-stream` |
| GET | `/api/fields/{field_id}/export.csv` | 200, `text/csv` |
| GET | `/api/projects/{project_id}/export.csv` | 200, `text/csv` |
| GET | `/api/fields/{field_id}/report.pdf` | 200, `application/pdf` |
| GET | `/api/projects/{project_id}/report.pdf` | 200, `application/pdf` |

Контракт ошибки расширен обратносовместимо: к прежнему полю `detail` добавлен
объект `error` со стабильным кодом и `request_id`. Прежние клиенты продолжают
читать `detail`, см. раздел 7.

## 3. Celery-задачи

Имена задач и очереди — внешний контракт: в очереди могут лежать сообщения,
опубликованные предыдущей версией. Переименование запрещено.

| Задача | Очередь | Аргументы | Побочные эффекты | Идемпотентность |
|---|---|---|---|---|
| `agropulse.tasks.pipeline.collect_field_data` | `collect` | `field_id: str` | `observations` (upsert), `fields.data_quality`, `jobs`, Redis pub/sub, внешние API | Да: upsert по `uq_observation_identity` |
| `agropulse.tasks.pipeline.analyze_field` | `analyze` | `field_id: str` | `observations` (restored/forecast — замещение), `anomalies`, `forecast_runs`, `fields.status/risk_*`, `jobs`, Redis pub/sub | Да: результаты анализа полностью замещаются |
| `agropulse.tasks.pipeline.process_field` | `collect` | `field_id: str` | сумма двух предыдущих | Да |

Ответы на обязательные вопросы гайда по каждой задаче:

* **Повторный запуск** — безопасен: наблюдения пишутся upsert'ом, результаты
  анализа удаляются и записываются заново в одной транзакции.
* **Падение посередине** — поле получает статус `failed` и причину в
  `data_quality.last_error`; запись не остаётся навсегда в промежуточном
  состоянии (`agropulse/services/pipeline.py:FieldPipeline.mark_failed`).
* **Временная ошибка** — `TransientPipelineError` (сеть, внешний источник,
  сервис моделей). Только она попадает в `autoretry_for`.
* **Окончательная ошибка** — всё остальное: некорректные данные, отсутствующее
  поле, ошибки программирования. Повтор не выполняется.
* **Как пользователь узнаёт** — статус поля, стадия `failed` в `jobs`
  и событие в SSE-потоке проекта.
* **Ограничение времени** — `soft_time_limit`/`time_limit` заданы на каждой
  задаче отдельно, а не только глобально.
* **Параллельность с собой** — допустима: две одновременные обработки одного
  поля приводят к одинаковому результату, потому что обе замещают данные
  целиком, а не наращивают их.

## 4. Таблицы

`projects`, `fields`, `observations`, `anomalies`, `forecast_runs`, `jobs`,
`scene_assets`, `raw_cache`. Схема описана в `agropulse/db/models.py`.

Ключевые инварианты закреплены в PostgreSQL, а не только в Python:

* `uq_observation_identity (field_id, date, value_type, source)` — ключ
  идемпотентности задачи сбора;
* `uq_job_field_stage (field_id, stage)` — одна строка прогресса на стадию;
* `uq_forecast_run_field (field_id)` — один актуальный прогон прогноза на поле;
* `ck_projects_period_order`, `ck_anomalies_period_order` — порядок дат;
* `ck_jobs_progress_range` — прогресс в пределах 0..1;
* `ck_observations_*` — индексы и доли в допустимых диапазонах;
* `ix_observations_field_type_date` — покрывает выборку ряда по типу значения.

## 5. Ключи Redis

| Ключ | Назначение | TTL | Можно потерять | Источник истины |
|---|---|---:|---|---|
| `agropulse:{env}:cache:v1:{provider}:{hash}` | Кэш ответов внешних API | 3 ч — 30 сут | Да | Внешний API + `raw_cache` |
| `agropulse:progress:{project_id}` | Pub/sub прогресса стадий | — | Да | Таблица `jobs` |
| очереди Celery | Брокер | — | Нет | Redis |

Брокер живёт в отдельной логической базе (`REDIS_DB_BROKER`), кэш и шина — в
своей (`REDIS_DB_CACHE`): вытеснение ключей кэша не должно затрагивать очередь.

Канал прогресса не переименовывался — на него подписаны открытые SSE-соединения.
Префикс ключей кэша изменён сознательно: это кэш с TTL, старые ключи истекут
сами, потери данных не происходит.

## 6. Внешние зависимости

| Источник | Модуль | Обязателен |
|---|---|---|
| Google Earth Engine (Sentinel-2) | `providers/satellite_gee.py` | Да, для сбора |
| STAC (резервный канал) | `providers/satellite_stac.py` | Нет, в цепочку не включён |
| Open-Meteo | `providers/weather_openmeteo.py` | Нет, погода — контекст |
| ERA5-Land через GEE | `providers/weather_era5_gee.py` | Нет, в цепочку не включён |
| Overpass API | `providers/parcels_overpass.py` | Нет |
| Nominatim | `providers/geocode_nominatim.py` | Нет |
| Сервис ML-моделей | `ml/http_client.py` | Да (временно допускается заглушка) |
| OpenRouter | `llm/openrouter.py` | Нет, без ключа текстов не будет |
| MinIO / S3 | `storage/s3.py` | Нет для расчёта, да для хранения отчётов |

## 7. Решения, принятые при рефакторинге

### 7.1. Что сохранено без изменений

* URL, методы, коды ответов и схемы запросов/ответов;
* имена Celery-задач, очередей и формат аргументов (строковый UUID);
* канал Redis pub/sub и формат событий SSE;
* применённая миграция `c9bd6d23f610` — новые ограничения добавлены
  отдельной миграцией, а не правкой существующей;
* поведение расчётов: климатология, аномалии, риск, прогноз, сверка чисел LLM.

### 7.2. Слои

```text
API router  → application service → repository / внешний клиент → PostgreSQL, Redis, HTTP
Celery task → application service → тот же слой ниже
```

Роутер занимается только HTTP: разбор пути, вызов сервиса, сериализация ответа.
Celery-задача — адаптер: разбирает аргументы, вызывает сервис, задаёт политику
повторов. Оба слоя ничего не знают про SQL.

Транзакцией управляет сервис через `UnitOfWork`; репозитории делают `add`,
`flush`, `execute`, но никогда не `commit`.

### 7.3. Ошибки

Бизнес-код возбуждает исключения из `agropulse/errors.py`, а не `HTTPException`.
Преобразование в HTTP выполняет обработчик в `agropulse/api/errors.py`.
У каждой ошибки есть стабильный код:

```json
{
  "detail": "поле не найдено",
  "error": {
    "code": "field_not_found",
    "message": "поле не найдено",
    "request_id": "01J..."
  }
}
```

Поле `detail` оставлено намеренно: это прежний контракт FastAPI, и клиенты,
написанные до рефакторинга, продолжают работать. Новое поле `error` даёт
машиночитаемый код и идентификатор запроса для поиска в логах.

### 7.4. Исправления поведения

Рефакторинг сохраняет поведение, но три дефекта были найдены по дороге и
исправлены отдельно от переноса кода. Каждый закрыт тестом.

1. **Смена контура оставляла чужие выводы.** `PATCH /api/fields/{id}` с новой
   геометрией удалял наблюдения, но не аномалии, прогноз и оценку риска.
   Пользователь видел на новом контуре события, найденные на старом. Теперь
   производные данные снимаются целиком и в одной транзакции с геометрией.
2. **Пароль попадал в `repr` настроек.** `database_url` был объявлен как
   `computed_field`, поэтому собранный из пароля DSN входил в представление
   объекта и в `model_dump`. `SecretStr` защищал пароль, но не строку
   подключения. Производные адреса стали обычными свойствами.
3. **Поле застревало в ожидании.** Упавшая задача не меняла статус поля,
   и оно навсегда оставалось `pending`. Теперь неудача даёт конечный статус
   `failed` с кодом ошибки.

Отдельно: `to_geojson` теперь принимает оба представления GeoAlchemy2.
Прежний код работал только с WKB, то есть с прочитанным из базы объектом;
только что записанное поле держит WKT, и ответ на POST собирался лишь потому,
что роутер делал дополнительный `refresh`.

### 7.5. Что сознательно не сделано

* **Переход на async SQLAlchemy.** Celery-воркер синхронный, и асинхронный
  движок дал бы две ветки кода ради одного SSE-эндпоинта, которому база не нужна.
* **Outbox для публикации задач.** Разрыв между `commit` и `delay` существует,
  но потерянная задача здесь означает лишь неначатую обработку поля, которую
  пользователь перезапускает кнопкой. Цена outbox (таблица, publisher, ещё один
  процесс) выше ущерба. Решение зафиксировано явно, а не пропущено.
* **Удаление `providers/satellite_stac.py` и `weather_era5_gee.py`.** Модули
  не в цепочке, но это проверенные резервные каналы, включаемые одной строкой
  в `providers/chain.py`. Мёртвым кодом они не являются.
* **Lock-файл зависимостей.** Версии закреплены совместимыми диапазонами
  (`~=`) в `pyproject.toml`. Полный lock требует отдельного инструмента и
  относится к сборке, а не к архитектуре сервиса.

## 8. Как проверить

```bash
cp .env.example .env
docker compose up -d --build          # postgres, redis, minio, migrate, api, 2 воркера
curl localhost:8000/health/ready      # {"status":"ok","checks":{"postgres":true,"s3":true}}
docker compose run --rm api pytest    # 93 теста
docker compose run --rm api ruff check .
```

Тесты делятся на две группы: модульные проверяют расчёты и не требуют
инфраструктуры, интеграционные создают отдельную базу `${POSTGRES_DB}_test`,
накатывают на неё миграции и удаляют её после прогона. Тем самым проверяется
и требование гайда «миграции применяются на пустой базе». При недоступном
PostgreSQL интеграционные тесты пропускаются, модульные продолжают работать.
