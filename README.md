# AgroPulse

Мониторинг сельхозполей по Sentinel-2: временной ряд NDVI, восстановление пропусков, аномалии, прогноз на 14 дней, реестр хозяйств и PDF-отчёты.

Как всё устроено — [`docs/`](docs/README.md).

---

## Развёрнутый стенд

<http://62.122.217.179> — логин `rostov`, пароль `G0r0D-Rostov-D0N`

| Параметр | Значение |
|---|---|
| ОС | Ubuntu 24.04 LTS 64-bit |
| vCPU | 8 × 2.2–2.4 ГГц, Hyper-Threading выключен |
| Память | 16 ГБ |
| Диск | 80 ГБ SSD |

Стенд работает, локально разворачивать не обязательно. Инструкция ниже — для запуска у себя.

---

## Требования

| Требование | Проверка |
|---|---|
| Docker Engine 24+ с Compose v2 | `docker compose version` |
| 8 ГБ на диске | `df -h .` |
| 4 ГБ оперативной памяти | `free -h` |
| Свободные порты 5173, 8000, 5432, 6379, 9000, 9001 | `ss -ltn` |
| Аккаунт Google Cloud | шаг 3 |

Больше ничего ставить не нужно.

---

# Перед запуском

## 1. Код

```bash
git clone git@github.com:jlik2002/AgroPulse.git agropulse
cd agropulse
```

Все команды — из корня репозитория.

## 2. Файл окружения

```bash
cp .env.example .env
```

Править две строки: `GEE_PROJECT` (шаг 3) и `OPENROUTER_API_KEY` (шаг 5).

## 3. Ключ Google Earth Engine

Обязателен. Без него интерфейс откроется, но обработка полей упадёт.

**3.1.** [Создайте проект](https://console.cloud.google.com) и скопируйте его **Project ID** (не название, например `agropulse-471203-k7`).

**3.2.** [Зарегистрируйте проект в Earth Engine](https://console.cloud.google.com/earth-engine) → *Register* → **noncommercial**.

**3.3.** [Включите Earth Engine API](https://console.cloud.google.com/apis/library/earthengine.googleapis.com) → *Enable*.

**3.4.** [Создайте сервис-аккаунт](https://console.cloud.google.com/iam-admin/serviceaccounts/create) с ролями **Earth Engine Resource Viewer** и **Service Usage Consumer**.

**3.5.** Сервис-аккаунт → *Keys* → *Add key* → *Create new key* → **JSON** → *Create*.

**3.6.** Положите файл под этим именем:

```bash
cp ~/Downloads/<файл>.json secrets/gee-service-account.json
```

**3.7.** Впишите в `.env` Project ID из 3.1:

```
GEE_PROJECT=agropulse-471203-k7
```

## 4. Опорный набор задачи 1 — необязательно

```bash
cp /путь/к/train_dataset.csv data/
```

Без него пропуски NDVI заполняются приближением по соседним точкам.

## 5. Ключ OpenRouter — необязательно

Ключ с <https://openrouter.ai/keys> в `.env`:

```
OPENROUTER_API_KEY=sk-or-v1-...
```

Без него считается всё, кроме текстовых пояснений.

---

# Запуск

## 1. Собрать и поднять

```bash
docker compose up -d --build
```

Первая сборка — 5–15 минут.

## 2. Дождаться готовности

```bash
docker compose ps
```

| Сервис | Состояние |
|---|---|
| `postgres`, `redis`, `minio`, `api`, `web` | `running (healthy)` |
| `worker-collect`, `worker-analyze` | `running` |
| `migrate` | `exited (0)` — одноразовая задача, так и должно быть |

## 3. Проверить

```bash
curl http://localhost:8000/health/ready
# {"status":"ok","checks":{"postgres":true,"s3":true}}

docker compose run --rm api python /app/scripts/check_gee.py

docker compose run --rm --no-deps api sh /app/scripts/check_network.sh
```

`check_gee.py` проходит путь до реальных снимков и называет шаг, на котором сломалось. В `check_network.sh` колонка `http`: `200` или `404` — хост отвечает, `000` — нет.

## 4. Открыть

| Адрес | Что |
|---|---|
| <http://localhost:5173> | интерфейс |
| <http://localhost:8000/docs> | API |
| <http://localhost:9001> | MinIO, логин и пароль — `S3_ACCESS_KEY` и `S3_SECRET_KEY` из `.env` |

Регистрации нет, проект привязывается к cookie. Справочник хозяйств заполнен миграцией — пять организаций доступны сразу.

## 5. Сценарий

1. **Поля** — найдите регион, возьмите контур из OpenStreetMap или нарисуйте свой, укажите хозяйство и культуру, задайте период.
2. **Проверка параметров** — отметьте поля для расчёта.
3. **Обработка** — прогресс по стадиям, поле открывается по готовности.
4. **Хозяйства** — реестр по индексу потребности в поддержке, карточка хозяйства, заключение PDF.
5. **Сводка** — карта и очередь на осмотр по полям.
6. **Поле** — обзор, снимки, динамика, данные.
7. **Прогноз** — 14 дней с коридором значений.
8. **Отчёты** — поле, хозяйство, реестр, сводка.

## Остановка

```bash
docker compose stop     # данные сохранятся
docker compose down     # удалить контейнеры, тома сохранятся
docker compose down -v  # удалить вместе с базой и хранилищем
```

---

# Batch-инференс (задача 1)

**1.** Положите файлы в `data/`:

```bash
cp private_features.csv train_dataset.csv data/
```

**2.** Сформируйте `submission.csv`:

```bash
docker compose run --rm --user "$(id -u):$(id -g)" api \
  python -m agropulse.cli predict \
    --input /app/data/private_features.csv \
    --output /app/data/submission.csv
```

**3.** Проверьте формат:

```bash
docker compose run --rm --user "$(id -u):$(id -g)" api \
  python -m agropulse.cli validate \
    --input /app/data/private_features.csv \
    --submission /app/data/submission.csv
```

Результат — `data/submission.csv`.

---

# Если не работает

| Симптом | Что делать |
|---|---|
| `port is already allocated` | Освободите порт или поменяйте левую часть в `ports` в `docker-compose.yml`. |
| `migrate` в `exited (1)` | `docker compose logs migrate` |
| `/health/ready` отдаёт `"s3":false` | `docker compose logs minio` |
| Обработка падает на сборе данных | Ключ GEE: проверка из шага 3, затем `docker compose logs worker-collect`. |
| Пустой ряд, поле «без данных» | Снимков за период нет или всё в облаках — расширьте период. |
| Внешние API недоступны, TLS виснет | Проверка `check_network.sh`. MTU занижен до 1400 намеренно, см. конец `docker-compose.yml`. |
| Пропуски восстановлены приближением | Нет `data/train_dataset.csv` — шаг 4. В логах `ml_v6_reference_missing`. |
| Нет текстовых пояснений | Не задан `OPENROUTER_API_KEY` — шаг 5. |
| Правки в задачах Celery не применяются | `docker compose restart worker-collect worker-analyze` |

Логи: `docker compose logs -f api worker-collect worker-analyze`

---

# Разработка

```bash
docker compose logs -f api                  # логи
docker compose restart worker-collect       # после правок задач Celery
docker compose run --rm api pytest          # тесты
docker compose run --rm api ruff check .    # линтер
```

Фронтенд вне контейнера:

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
npm run typecheck
npm run build
```

Адрес бэкенда для прокси — `VITE_API_PROXY`, по умолчанию `http://localhost:8000`.

Новая миграция:

```bash
docker compose run --rm --user "$(id -u):$(id -g)" migrate \
  alembic revision --autogenerate -m "описание"
docker compose run --rm migrate alembic upgrade head
```
