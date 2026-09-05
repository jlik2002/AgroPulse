# API

База — `/api`. Интерактивная документация: <http://localhost:8000/docs>.

## Проекты

| Метод | Путь | Что |
|---|---|---|
| POST | `/projects` | создать, период не короче 14 дней |
| GET | `/projects` | проекты посетителя и демонстрационный |
| GET | `/projects/{id}` | без проверки владельца: ссылка и есть ключ доступа |
| PATCH | `/projects/{id}` | название, период |
| DELETE | `/projects/{id}` | каскадом с полями и данными |

## Хозяйства

| Метод | Путь | Что |
|---|---|---|
| POST | `/farms` | завести в общем справочнике |
| GET | `/farms` | весь справочник по алфавиту |
| GET/PATCH | `/farms/{id}` | реквизиты |
| DELETE | `/farms/{id}` | поля остаются, отвечает числом осиротевших |
| GET | `/projects/{pid}/farms/{fid}/summary` | индекс, достоверность, очередь полей |
| GET | `/projects/{id}/registry` | реестр приоритетной поддержки |

## Поля

| Метод | Путь | Что |
|---|---|---|
| POST | `/projects/{id}/fields` | `farm_id` и `crop` обязательны |
| GET | `/projects/{id}/fields` | список |
| GET/PATCH/DELETE | `/fields/{id}` | |
| GET | `/fields/{id}/timeseries` | ряд со сводкой качества данных |
| POST | `/fields/{id}/process` | 202, обработка в очередь |
| POST | `/projects/{id}/process` | без тела — весь проект, со списком — выбранные поля |

## Результаты

| Метод | Путь | Что |
|---|---|---|
| GET | `/fields/{id}/anomalies` | периоды, тяжёлые первыми |
| GET | `/fields/{id}/risk` | балл, вклад факторов, уверенность |
| GET | `/fields/{id}/radar` | ряд Sentinel-1 и события в нём |
| GET | `/fields/{id}/forecast` | прогноз на 14 дней, `null` — штатный ответ |
| GET | `/projects/{id}/summary` | сводка и очередь на осмотр |
| GET | `/projects/{id}/events` | SSE: прогресс по стадиям |

## Документы

| Метод | Путь | Что |
|---|---|---|
| GET | `/fields/{id}/report.pdf` | параметр `sections` через запятую |
| GET | `/projects/{pid}/farms/{fid}/report.pdf` | заключение по хозяйству |
| GET | `/projects/{id}/registry.pdf` \| `.csv` | реестр |
| GET | `/projects/{id}/report.pdf` | сводка по полям |
| GET | `/fields/{id}/export.csv` | ряд поля |
| GET | `/projects/{id}/export.csv` | ряды всех полей |
| GET | `/projects/{id}/reports` \| `/farms/{id}/reports` | список сформированного |
| GET | `/reports/{id}/download` | сохранённая версия |

## Территория

| Метод | Путь | Что |
|---|---|---|
| GET | `/regions/search` | геокодер, минимум 2 символа |
| POST | `/parcels/search` | контуры пашни в прямоугольнике карты |

## Пробы

`/health/live` и `/health/ready` живут вне префикса `/api`: их дёргает инфраструктура. `ready` проверяет PostgreSQL и S3.

## Ошибки

```json
{"error": {"code": "farm_not_found", "message": "хозяйство не найдено", "request_id": "..."}}
```

Код стабилен и годится для поиска инцидента в логах, сообщение предназначено человеку и может меняться. Каждый ответ несёт заголовок `X-Request-ID`; переданный клиентом сохраняется.
