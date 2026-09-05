# Гайд по рефакторингу существующего сервиса

Стек:

- Python;
- FastAPI;
- Celery;
- Redis;
- PostgreSQL;
- Docker.

## 1. Главная цель

Нужно преобразовать существующий код так, чтобы:

- сервис продолжал выполнять текущие бизнес-функции;
- публичные API-контракты не ломались без явного решения;
- Celery-задачи не терялись и корректно переживали повторный запуск;
- транзакции PostgreSQL были предсказуемыми;
- Redis использовался с понятной целью;
- код был разделён на логические слои;
- любую бизнес-операцию можно было протестировать отдельно;
- ошибки можно было диагностировать по логам и метрикам;
- сервис можно было локально поднять одной командой;
- дальнейшие изменения не требовали снова переписывать половину проекта.

Итоговая цель — не максимальное количество паттернов, а понятный код с контролируемыми зависимостями.

## 2. Основные правила переделывания

### 2.1. Не переписывать всё сразу

Нельзя одновременно:

- менять структуру проекта;
- переписывать ORM-модели;
- менять API-контракты;
- менять Celery broker;
- переходить с sync на async;
- обновлять все зависимости;
- переписывать Docker;
- добавлять новую бизнес-функциональность.

Иначе невозможно понять, где возникла ошибка.

Работа должна выполняться поэтапно:

```text
Зафиксировать поведение
→ стабилизировать запуск
→ отделить конфигурацию
→ выделить бизнес-операции
→ исправить транзакции
→ исправить Celery
→ привести в порядок Redis
→ добавить тесты и наблюдаемость
→ удалить старый код
```

### 2.2. Сначала сохранить поведение, потом улучшать его

Перед изменением функции нужно понять:

- кто её вызывает;
- какие аргументы передаются;
- какие побочные эффекты она создаёт;
- какие записи создаёт в БД;
- какие исключения выбрасывает;
- какие Celery-задачи публикует;
- что записывает в Redis;
- какой HTTP-ответ получает пользователь.

Если текущее поведение странное, но используется другими компонентами, сначала его нужно зафиксировать тестом. Исправление поведения выполняется отдельно.

### 2.3. Не совмещать рефакторинг и изменение логики

Плохо:

```text
Перенесли функцию
+ изменили статус ответа
+ переписали SQL
+ поменяли retry
+ переименовали endpoint
```

Хорошо:

1. Перенесли функцию без изменения поведения.
2. Добавили тесты.
3. Отдельно исправили SQL.
4. Отдельно изменили API-контракт.
5. Отдельно настроили retry.

### 2.4. Каждое изменение должно оставлять сервис рабочим

После каждого этапа должно быть возможно:

- собрать Docker image;
- запустить сервис;
- применить миграции;
- выполнить базовый API-запрос;
- запустить Celery worker;
- выполнить хотя бы одну фоновую задачу;
- прогнать тесты.

## 3. Этап 0. Провести инвентаризацию

До изменения кода нужно составить карту сервиса.

### 3.1. Найти точки входа

Нужно определить:

- где создаётся FastAPI application;
- где подключаются routers;
- где создаётся Celery application;
- как запускается worker;
- есть ли Celery Beat;
- где создаётся SQLAlchemy engine;
- где создаётся Redis client;
- где загружаются настройки;
- как выполняются миграции;
- какие команды запускаются в Docker.

Результат можно оформить так:

```text
FastAPI:
  app/main.py:create_app

Celery:
  app/worker.py:celery_app

PostgreSQL:
  app/database.py:engine
  migrations: alembic/

Redis:
  app/redis.py:redis_client

Commands:
  API: uvicorn app.main:app
  Worker: celery -A app.worker worker
  Beat: celery -A app.worker beat
```

### 3.2. Составить список компонентов

Нужно найти:

- все HTTP endpoints;
- все Celery tasks;
- все таблицы;
- все Redis keys;
- все внешние API;
- все периодические задачи;
- все filesystem/S3 операции;
- все environment variables.

Особенно важно найти скрытые зависимости:

```python
from app.main import redis
from app.worker import celery
from app.database import session
```

Такие импорты часто создают:

- циклические зависимости;
- соединения во время импорта;
- проблемы тестирования;
- разное поведение API и worker;
- невозможность переиспользования кода.

### 3.3. Зафиксировать внешние контракты

До рефакторинга необходимо сохранить:

- URL endpoints;
- HTTP-методы;
- request schemas;
- response schemas;
- HTTP-коды;
- названия Celery tasks;
- названия очередей;
- формат аргументов задач;
- Redis key format;
- текущую схему PostgreSQL;
- формат внешних webhook;
- формат событий и сообщений.

Например, изменение имени задачи:

```python
@celery_app.task(name="reports.generate")
```

может сломать уже находящиеся в очереди сообщения. Поэтому task name нельзя случайно менять вместе с переносом функции в другой модуль.

## 4. Этап 1. Добиться воспроизводимого запуска

До архитектурного рефакторинга сервис должен стабильно запускаться.

### Должны работать команды

```bash
docker compose up --build
docker compose run --rm api alembic upgrade head
docker compose run --rm api pytest
```

Минимально должны запускаться:

- PostgreSQL;
- Redis;
- FastAPI;
- Celery worker;
- Celery Beat, если используется.

### Что исправить первым

- отсутствующие переменные окружения;
- неправильные импорты;
- зависимости, не закреплённые по версиям;
- миграции, которые не накатываются на пустую БД;
- подключение к `localhost` из контейнера;
- запуск от случайной рабочей директории;
- ручные действия, не описанные в README;
- создание таблиц через `Base.metadata.create_all()` вместо миграций.

### Результат этапа

Новый разработчик должен иметь возможность:

```bash
git clone ...
cp .env.example .env
docker compose up --build
```

и получить работающий сервис без ручного создания таблиц или выполнения неизвестных скриптов.

## 5. Этап 2. Зафиксировать текущее поведение тестами

Если код плохой, сначала нужны characterization tests — тесты, которые описывают фактическое поведение, даже если оно неидеально.

### Что покрыть в первую очередь

Выбирать нужно не по файлам, а по риску:

1. Создание и изменение критичных сущностей.
2. Денежные или биллинговые операции.
3. Публикация Celery-задач.
4. Повторное выполнение задач.
5. Интеграции с внешними API.
6. Авторизация.
7. Генерация файлов и отчётов.
8. Периодические задачи.
9. Webhook.

### Минимальный smoke test

```python
def test_healthcheck(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
```

### Тест существующего API-контракта

```python
def test_create_report_preserves_existing_contract(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/reports",
        json={
            "field_id": "018f...",
            "date_from": "2026-06-01",
            "date_to": "2026-06-30",
        },
    )

    assert response.status_code == 202
    assert response.json() == {
        "id": ANY,
        "status": "pending",
    }
```

### Тест побочных эффектов

Нужно проверять не только ответ API:

```python
def test_create_report_saves_job_and_schedules_task(
    client: TestClient,
    session: Session,
    celery_mock: Mock,
) -> None:
    response = client.post("/api/reports", json=payload)

    report_id = response.json()["id"]

    report = session.get(ReportModel, report_id)
    assert report.status == ReportStatus.PENDING

    celery_mock.send_task.assert_called_once()
```

После появления этих тестов внутренний код можно переносить и переписывать, сохраняя внешнее поведение.

## 6. Этап 3. Привести в порядок конфигурацию

Обычно в старом сервисе настройки разбросаны:

```python
redis_url = os.getenv("REDIS_URL")
timeout = int(os.getenv("TIMEOUT", 30))
debug = os.getenv("DEBUG") == "true"
```

Это нужно заменить единым типизированным объектом.

```python
class Settings(BaseSettings):
    environment: Literal["local", "test", "stage", "prod"]

    database_url: PostgresDsn
    redis_url: RedisDsn
    celery_broker_url: str
    celery_result_backend: str | None = None

    external_api_timeout_seconds: PositiveFloat = 10
    report_task_soft_limit_seconds: PositiveInt = 300

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )
```

### Правила

- Настройки читаются в одном месте.
- Бизнес-код не вызывает `os.getenv()`.
- Обязательные настройки не имеют опасных значений по умолчанию.
- Секреты не лежат в коде.
- Приложение падает при старте, если конфигурация некорректна.
- `.env.example` содержит все необходимые переменные без реальных значений.
- В логах не выводится полный объект настроек.

### Не нужно

Создавать новый `Settings()` в каждом модуле:

```python
settings = Settings()
```

Лучше создать настройки один раз при сборке приложения и передать их компонентам.

## 7. Этап 4. Разделить код по ответственности

Основная проблема старого FastAPI-сервиса обычно выглядит так:

```python
@router.post("/reports")
async def create_report(request: Request):
    data = await request.json()

    session = SessionLocal()

    field = session.query(Field).filter(...).first()

    if not field:
        return JSONResponse(...)

    redis.set(...)

    response = requests.get(...)

    report = Report(...)
    session.add(report)
    session.commit()

    generate_report.delay(report.id)

    return {...}
```

Здесь смешаны:

- HTTP;
- валидация;
- SQL;
- бизнес-логика;
- Redis;
- внешний API;
- транзакция;
- Celery;
- сериализация ответа.

### Целевая структура

```text
API layer
    ↓
Application service / use case
    ↓
Repositories and external clients
    ↓
PostgreSQL / Redis / external API
```

### API layer

Отвечает только за HTTP:

```python
@router.post(
    "/reports",
    response_model=ReportResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_report(
    payload: CreateReportRequest,
    current_user: CurrentUserDep,
    service: ReportServiceDep,
) -> ReportResponse:
    report = await service.create_report(
        CreateReportCommand(
            user_id=current_user.id,
            field_id=payload.field_id,
            date_from=payload.date_from,
            date_to=payload.date_to,
        )
    )

    return ReportResponse.model_validate(report)
```

### Application service

Описывает бизнес-сценарий:

```python
class ReportService:
    def __init__(
        self,
        unit_of_work: UnitOfWork,
        task_publisher: TaskPublisher,
    ) -> None:
        self._uow = unit_of_work
        self._task_publisher = task_publisher

    async def create_report(
        self,
        command: CreateReportCommand,
    ) -> Report:
        async with self._uow:
            field = await self._uow.fields.get(command.field_id)

            if field is None:
                raise FieldNotFoundError(command.field_id)

            if field.owner_id != command.user_id:
                raise FieldNotFoundError(command.field_id)

            report = Report.create(
                field_id=field.id,
                date_from=command.date_from,
                date_to=command.date_to,
            )

            await self._uow.reports.add(report)
            await self._uow.outbox.add(
                ReportGenerationRequested(report_id=report.id)
            )

            await self._uow.commit()

        return report
```

### Repository

Содержит только работу с хранилищем:

```python
class SqlAlchemyReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, report_id: UUID) -> ReportModel | None:
        return await self._session.get(ReportModel, report_id)

    async def add(self, report: ReportModel) -> None:
        self._session.add(report)
        await self._session.flush()
```

### Важное ограничение

Не нужно сразу переносить весь проект в новую структуру.

Рефакторинг выполняется вертикальными срезами:

```text
Сначала create_report полностью
→ потом get_report
→ потом delete_report
→ потом следующий бизнес-модуль
```

Так старый и новый код могут временно существовать одновременно.

## 8. Этап 5. Сделать FastAPI-слой тонким

### Из роутеров необходимо убрать

- прямые SQL-запросы;
- управление транзакциями;
- работу с Redis;
- прямой вызов внешних API;
- большие `try/except`;
- бизнес-условия;
- создание файлов;
- долгие вычисления;
- ручной разбор JSON;
- создание глобальных клиентов.

### API-схемы отделить от ORM

Плохо:

```python
@router.get("/users/{user_id}")
async def get_user(user_id: int) -> UserModel:
    return await session.get(UserModel, user_id)
```

Лучше:

```python
class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
```

ORM-модель может содержать:

- password hash;
- internal flags;
- service fields;
- relationships;
- поля, которые нельзя раскрывать.

### Ошибки сделать централизованными

Бизнес-код не должен создавать `HTTPException`.

Плохо:

```python
class ReportService:
    async def get(self, report_id: UUID):
        report = await self.repository.get(report_id)
        if report is None:
            raise HTTPException(status_code=404)
```

Лучше:

```python
if report is None:
    raise ReportNotFoundError(report_id)
```

А преобразование в HTTP выполнить через exception handler.

## 9. Этап 6. Исправить PostgreSQL и транзакции

### Найти все `commit()`

Нужно выполнить поиск:

```bash
rg "\.commit\(" app
```

И проверить каждый вызов.

Частая проблема:

```python
repository.create_user()
repository.commit()

repository.create_profile()
repository.commit()

repository.create_subscription()
repository.commit()
```

Если создание подписки упадёт, пользователь останется в частично созданном состоянии.

Должно быть:

```python
async with session.begin():
    user = await user_repository.create(...)
    profile = await profile_repository.create(user.id, ...)
    subscription = await subscription_repository.create(user.id, ...)
```

### Граница транзакции

Транзакция должна соответствовать бизнес-операции.

```text
«Создать пользователя»
    ├── создать users
    ├── создать profile
    ├── сохранить audit event
    └── commit
```

Repository не должен самовольно выполнять `commit()`.

Допустимы:

- `add`;
- `flush`;
- `refresh`;
- `execute`;
- `get`.

Но решение о `commit/rollback` принимает верхний слой.

### Проверить бизнес-инварианты

Если код делает:

```python
if not await repository.exists(email):
    await repository.create(email)
```

необходимо добавить `UNIQUE` в PostgreSQL. Иначе два параллельных запроса создадут дубликаты.

В БД должны находиться:

- `NOT NULL`;
- `UNIQUE`;
- foreign keys;
- `CHECK`;
- уникальные idempotency keys.

### Устранить N+1

Подозрительный код:

```python
users = await repository.get_users()

for user in users:
    subscriptions.append(
        await subscription_repository.get_by_user_id(user.id)
    )
```

Нужно заменить:

- join;
- eager loading;
- batch query;
- `WHERE user_id IN (...)`.

### Проверить время жизни session

SQLAlchemy session нельзя:

- хранить глобально;
- переиспользовать между запросами;
- передавать между потоками;
- передавать в Celery;
- использовать после закрытия;
- разделять между параллельными coroutine.

HTTP-запрос и Celery-задача должны получать собственную session.

## 10. Этап 7. Переделать Celery-задачи

Celery-код следует считать небезопасным, пока не доказано обратное.

### Сначала составить таблицу задач

| Task | Аргументы | Side effects | Retry | Идемпотентность |
|---|---|---|---|---|
| `reports.generate` | `report_id` | файл, PostgreSQL | Да | Нужно проверить |
| `emails.send` | `email_id` | внешний email API | Да | По provider ID |
| `cache.rebuild` | `field_id` | Redis | Да | Идемпотентна |

Для каждой задачи нужно ответить:

- Что произойдёт при повторном запуске?
- Что произойдёт при падении посередине?
- Какая ошибка временная?
- Какая ошибка окончательная?
- Как пользователь узнает о неудаче?
- Есть ли ограничение времени?
- Может ли задача выполняться параллельно сама с собой?

### Celery task должна быть адаптером

```python
@celery_app.task(
    name="reports.generate",
    bind=True,
    autoretry_for=(TemporaryExternalError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
    soft_time_limit=300,
    time_limit=330,
)
def generate_report_task(
    self: Task,
    report_id: str,
) -> None:
    container = build_worker_container()
    container.report_generator.generate(UUID(report_id))
```

Основная логика должна быть обычным Python-методом.

### Передавать только идентификаторы

Нужно убрать из аргументов задач:

- ORM-объекты;
- открытые соединения;
- request objects;
- большие JSON;
- содержимое файлов;
- нестабильные внутренние структуры.

Передавать:

```python
generate_report_task.delay(str(report_id))
```

Worker сам загружает актуальные данные из PostgreSQL.

### Сделать задачи идемпотентными

Плохо:

```python
def charge_user(user_id: UUID, amount: Decimal) -> None:
    payment_provider.charge(user_id, amount)
```

При повторном выполнении произойдёт двойное списание.

Лучше:

```python
def charge_user(payment_id: UUID) -> None:
    payment = repository.get_for_update(payment_id)

    if payment.status == PaymentStatus.COMPLETED:
        return

    result = payment_provider.charge(
        customer_id=payment.customer_id,
        amount=payment.amount,
        idempotency_key=str(payment.id),
    )

    payment.mark_completed(provider_payment_id=result.id)
```

Идемпотентность должна поддерживаться:

- уникальным operation ID;
- constraint в PostgreSQL;
- idempotency key внешнего API;
- atomic update;
- блокировкой строки;
- детерминированным результатом.

### Разделить ошибки

```python
class TemporaryReportGenerationError(Exception):
    pass


class InvalidReportDataError(Exception):
    pass
```

Retry только для временной ошибки:

```python
autoretry_for=(TemporaryReportGenerationError,)
```

Нельзя делать:

```python
autoretry_for=(Exception,)
```

Так будут повторяться:

- ошибки программирования;
- неправильные данные;
- нарушение бизнес-правил;
- отсутствующая конфигурация.

### Добавить конечное состояние ошибки

Не должно быть записи, навечно оставшейся в `processing`.

```python
try:
    generator.generate(report_id)
except TemporaryReportGenerationError:
    raise
except Exception:
    report_service.mark_failed(
        report_id=report_id,
        error_code="generation_failed",
    )
    raise
```

Не следует хранить полный traceback в пользовательском поле. Детали остаются в логах, пользователю возвращается безопасный error code.

### Исправить публикацию задач после транзакции

Проблема:

```python
await session.commit()
generate_report.delay(report.id)
```

Между двумя строками процесс может упасть.

Для важных операций нужен outbox:

```sql
CREATE TABLE outbox_events (
    id UUID PRIMARY KEY,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ
);
```

В одной транзакции:

```python
async with session.begin():
    session.add(report)
    session.add(
        OutboxEvent(
            event_type="report_generation_requested",
            payload={"report_id": str(report.id)},
        )
    )
```

Отдельный publisher публикует события в Celery.

## 11. Этап 8. Привести Redis к понятной модели

Нужно найти все обращения:

```bash
rg "redis|setex|expire|hset|lpush|rpush|publish" app
```

И классифицировать каждый ключ:

| Ключ | Назначение | TTL | Можно потерять | Источник истины |
|---|---|---:|---|---|
| `user:{id}` | Cache | 5 минут | Да | PostgreSQL |
| `report:{id}:lock` | Lock | 10 минут | Да | PostgreSQL |
| Celery queue | Broker | Нет | Нет | Redis/Celery |
| `session:{id}` | Session | 30 дней | Зависит | Redis |

### Ввести единый namespace

```python
def report_cache_key(report_id: UUID) -> str:
    return f"service:prod:report:{report_id}:v1"
```

Не создавать ключи вручную в разных модулях:

```python
f"report_{id}"
f"reports:{id}"
f"report-{id}"
```

### Добавить TTL

Любой cache должен иметь срок жизни:

```python
await redis.set(
    report_cache_key(report.id),
    report_json,
    ex=settings.report_cache_ttl_seconds,
)
```

Если TTL отсутствует, это должно быть явно обосновано.

### Cache не должен ломать основную операцию

Для большинства обычных cache:

```python
try:
    cached = await cache.get(key)
except RedisError:
    logger.warning("cache_read_failed", extra={"key": safe_key})
    cached = None
```

Недоступность cache обычно не должна превращать весь API в `500`, если данные можно получить из PostgreSQL.

Это не относится к Redis, используемому как broker, lock или основное хранилище состояния.

### Исправить lock

Нужны:

- уникальный token владельца;
- TTL;
- атомарное освобождение только владельцем;
- обработка истечения TTL;
- идемпотентность защищаемой операции.

Redis lock не должен быть единственной защитой важного бизнес-инварианта. Основную гарантию желательно закрепить в PostgreSQL.

### Разделить cache и Celery broker

Если возможно:

```text
redis-cache
redis-celery
```

Минимум — разные логические пространства, credentials и настройки.

Cache может иметь eviction policy, а очередь не должна неожиданно потерять сообщения из-за вытеснения ключей.

## 12. Этап 9. Исправить Docker

### Целевое состояние

Один image используется для:

- FastAPI;
- Celery worker;
- Celery Beat;
- миграций.

Отличаются только команды запуска.

```yaml
services:
  api:
    image: service:${IMAGE_TAG}
    command: ["uvicorn", "app.main:create_app", "--factory", "--host=0.0.0.0"]

  worker:
    image: service:${IMAGE_TAG}
    command: ["celery", "--app=app.tasks.celery_app", "worker"]

  beat:
    image: service:${IMAGE_TAG}
    command: ["celery", "--app=app.tasks.celery_app", "beat"]

  migration:
    image: service:${IMAGE_TAG}
    command: ["alembic", "upgrade", "head"]
```

### Необходимо устранить

- запуск от root;
- секреты через `ENV` в Dockerfile;
- установку компилятора в runtime image;
- копирование всего проекта до установки зависимостей;
- `pip install` без lock-файла;
- shell-form `CMD`;
- несколько независимых Dockerfile без необходимости;
- запуск migrations при старте каждого API instance;
- `sleep 10 && start-app`;
- публикацию PostgreSQL и Redis в интернет;
- development volume mounts в production.

### Graceful shutdown

FastAPI и Celery должны получать `SIGTERM`.

Нельзя запускать так:

```dockerfile
CMD uvicorn app.main:app
```

Лучше:

```dockerfile
CMD ["uvicorn", "app.main:create_app", "--factory", "--host=0.0.0.0", "--port=8000"]
```

Если используется shell script, он должен передавать управление через `exec`.

## 13. Этап 10. Унифицировать ошибки и логи

### Запретить бессмысленные сообщения

Плохо:

```python
logger.info("here")
logger.info("started")
logger.error(str(exc))
```

Хорошо:

```python
logger.info(
    "report_generation_started",
    extra={
        "report_id": str(report_id),
        "task_id": task_id,
    },
)
```

```python
logger.exception(
    "report_generation_failed",
    extra={
        "report_id": str(report_id),
        "task_id": task_id,
        "attempt": retry_count,
    },
)
```

### Не логировать одно исключение несколько раз

Ошибка должна логироваться там, где:

- она окончательно обрабатывается;
- к ней добавляется важный контекст;
- она превращается во внешний ответ.

Не нужно логировать её в repository, service, router и middleware одновременно.

### Ввести correlation IDs

Каждый запрос должен иметь:

- `request_id`;
- `trace_id`, если есть tracing.

Для Celery:

- `task_id`;
- `root_task_id`;
- исходный `request_id`, если задача создана из HTTP-запроса.

### Ввести стабильные error codes

```python
class ReportGenerationFailedError(AppError):
    code = "report_generation_failed"
```

HTTP-ответ:

```json
{
  "error": {
    "code": "report_generation_failed",
    "message": "The report could not be generated",
    "request_id": "01J..."
  }
}
```

## 14. Этап 11. Убрать дублирование и плохие abstractions

После разделения слоёв можно заниматься локальной чисткой.

### Удалить

- неиспользуемые функции;
- закомментированный код;
- мёртвые endpoints;
- дублирующиеся Pydantic schemas;
- старые Celery tasks;
- бессмысленные wrappers;
- глобальные singleton connections;
- универсальные `helpers.py`;
- копии SQL-запросов;
- повторяющуюся обработку исключений;
- неиспользуемые environment variables.

### Осторожно с «универсальными» базовыми классами

Плохо:

```python
class BaseRepository(Generic[T]):
    async def get(...)
    async def create(...)
    async def update(...)
    async def delete(...)
```

Если каждый repository потом обходит этот интерфейс или формирует сложные `filter_by`, базовый repository только скрывает SQL.

Лучше выражать бизнес-запросы:

```python
class ReportRepository:
    async def get_pending_for_update(
        self,
        report_id: UUID,
    ) -> Report | None:
        ...

    async def find_by_field_and_period(
        self,
        field_id: UUID,
        date_from: date,
        date_to: date,
    ) -> Report | None:
        ...
```

## 15. Целевой стандарт читаемости

После рефакторинга код должен читаться сверху вниз как описание операции.

```python
async def create_report(
    self,
    command: CreateReportCommand,
) -> Report:
    self._validate_period(command.date_from, command.date_to)

    async with self._unit_of_work:
        field = await self._get_owned_field(
            field_id=command.field_id,
            user_id=command.user_id,
        )

        await self._ensure_report_does_not_exist(
            field_id=field.id,
            date_from=command.date_from,
            date_to=command.date_to,
        )

        report = Report.create(
            field_id=field.id,
            date_from=command.date_from,
            date_to=command.date_to,
        )

        await self._unit_of_work.reports.add(report)
        await self._unit_of_work.outbox.add(
            ReportGenerationRequested(report.id)
        )
        await self._unit_of_work.commit()

    return report
```

Человек должен понимать основной сценарий, не погружаясь сразу в:

- SQLAlchemy;
- Redis;
- HTTP;
- Celery;
- сериализацию;
- логирование.

## 16. Порядок рефакторинга одного бизнес-сценария

Для каждого endpoint или Celery task использовать один процесс.

### Шаг 1. Описать текущее поведение

```text
POST /reports:

1. Проверяет field_id.
2. Создаёт reports со статусом pending.
3. Записывает status в Redis.
4. Публикует reports.generate.
5. Возвращает 202.
```

### Шаг 2. Добавить тест текущего поведения

Проверить:

- HTTP-ответ;
- запись в PostgreSQL;
- Celery publish;
- Redis side effect;
- ошибочные сценарии.

### Шаг 3. Выделить request/response schemas

Убрать ручную работу со словарями.

### Шаг 4. Выделить application service

Перенести бизнес-сценарий из router/task.

### Шаг 5. Выделить repository и clients

Перенести SQL, Redis и внешний HTTP.

### Шаг 6. Исправить транзакцию

Объединить атомарные действия.

### Шаг 7. Исправить Celery

Добавить:

- idempotency;
- retry policy;
- time limits;
- итоговый failure status.

### Шаг 8. Добавить observability

- бизнес-события в логах;
- duration;
- error code;
- task/request ID;
- метрики.

### Шаг 9. Удалить старую реализацию

Только после того, как новый путь полностью используется.

## 17. Что нельзя делать при переделывании

Нельзя без отдельного обоснования:

- переписывать сервис с нуля;
- менять все sync-функции на async;
- добавлять repository к каждой таблице;
- создавать интерфейс для каждого класса;
- переносить бизнес-логику в ORM-модели без необходимости;
- менять API «потому что так красивее»;
- переименовывать Celery tasks;
- изменять Redis keys без стратегии миграции;
- пересоздавать миграции, уже применённые в production;
- менять тип первичных ключей одной миграцией;
- ловить все исключения;
- retry все исключения;
- добавлять cache без измеренной необходимости;
- добавлять distributed lock вместо исправления транзакции;
- проводить оптимизацию без профилирования;
- обновлять все зависимости вместе с архитектурным рефакторингом.

## 18. Критерии завершённого рефакторинга

Переделывание можно считать завершённым, когда:

### Запуск

- сервис собирается в Docker;
- локальное окружение запускается одной командой;
- миграции применяются отдельно;
- API и Celery используют один image;
- все необходимые переменные описаны.

### Архитектура

- routers содержат только HTTP-логику;
- Celery tasks являются тонкими адаптерами;
- бизнес-сценарии находятся в services/use cases;
- SQL изолирован в repositories;
- внешние API представлены отдельными clients;
- конфигурация централизована;
- нет глобальных DB sessions.

### PostgreSQL

- транзакции соответствуют бизнес-операциям;
- repository не выполняют неожиданный `commit`;
- инварианты защищены constraints;
- устранены основные N+1;
- критичные запросы имеют подходящие индексы;
- миграции работают на пустой и существующей БД.

### Celery

- задачи идемпотентны;
- передаются идентификаторы, а не большие объекты;
- retry ограничен;
- есть timeouts;
- permanent errors не повторяются;
- после ошибки сохраняется конечный статус;
- учтён разрыв между PostgreSQL и публикацией задачи.

### Redis

- назначение каждого ключа известно;
- cache имеет TTL;
- ключи имеют namespace;
- нет `KEYS`;
- lock освобождается только владельцем;
- потеря cache не повреждает основные данные;
- broker и cache не конфликтуют по памяти и eviction.

### Качество

- основная логика типизирована;
- функции имеют понятные названия;
- исключения не проглатываются;
- нет `utils.py` на тысячу строк;
- отсутствует мёртвый код;
- комментарии объясняют причины решений;
- ключевые сценарии покрыты тестами.

### Эксплуатация

- есть health endpoints;
- есть структурированные логи;
- есть request/task IDs;
- секреты не логируются;
- измеряется latency;
- измеряются ошибки и retry;
- можно понять причину падения без изменения кода.

## 19. Короткая инструкция для исполнителя

Этот блок можно использовать непосредственно как требования к разработчику или кодовому агенту:

```markdown
Не переписывай сервис с нуля. Переделывай его постепенно,
сохраняя существующие внешние контракты и поведение.

Перед изменением каждого компонента:

1. Найди все места его использования.
2. Опиши текущее поведение и побочные эффекты.
3. Добавь characterization tests.
4. Выполни минимальный рефакторинг.
5. Запусти тесты и сервис.
6. Только после этого исправляй само поведение.

Целевая архитектура:

- FastAPI routers отвечают только за HTTP.
- Application services реализуют бизнес-сценарии.
- Repositories инкапсулируют PostgreSQL.
- External clients инкапсулируют внешние API.
- Celery tasks являются тонкими адаптерами.
- Redis используется только через специализированные компоненты.
- Транзакцией управляет application service.
- Конфигурация централизована и типизирована.

Не изменяй без отдельного решения:

- публичные HTTP-контракты;
- названия Celery tasks и очередей;
- формат Celery-сообщений;
- существующие Redis keys;
- уже применённые миграции;
- бизнес-поведение.

Все Celery-задачи должны быть идемпотентными, иметь ограниченный
retry, backoff, timeout и конечный статус ошибки.

Все критичные бизнес-инварианты должны быть защищены PostgreSQL
constraints, а не только Python-проверками.

После каждого этапа должны успешно работать:

- сборка Docker image;
- запуск Docker Compose;
- применение миграций;
- запуск FastAPI;
- запуск Celery worker;
- unit и integration tests.

Не добавляй абстракции без реальной необходимости. Читаемость,
предсказуемость и безопасность важнее формального следования
архитектурным паттернам.
```
