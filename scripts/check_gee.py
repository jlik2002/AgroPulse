"""Проверка доступа к Google Earth Engine.

Скрипт проходит всю цепочку до реальных данных: читает ключ сервис-аккаунта,
инициализирует Earth Engine и считает средний NDVI по тестовому полигону.
Смысл в том, чтобы обнаружить проблему с доступом сейчас, а не на этапе,
когда она замаскируется под пустой временной ряд.

Запуск:
    docker compose run --rm api python /app/scripts/check_gee.py
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from agropulse.config import get_settings  # noqa: E402

# Небольшой участок пашни в Краснодарском крае — только для проверки доступа.
TEST_POLYGON = [
    [39.00, 45.00],
    [39.02, 45.00],
    [39.02, 45.02],
    [39.00, 45.02],
    [39.00, 45.00],
]


def fail(message: str, hint: str = "") -> None:
    print(f"\n[ОШИБКА] {message}")
    if hint:
        print(f"         {hint}")
    sys.exit(1)


def main() -> None:
    settings = get_settings()
    key_path = Path(settings.gee_service_account_file)

    print("1/5  Ключ сервис-аккаунта")
    if not key_path.is_file():
        fail(
            f"файл не найден: {key_path}",
            "Положите JSON-ключ в secrets/gee-service-account.json — см. README.",
        )
    try:
        key_data = json.loads(key_path.read_text())
    except json.JSONDecodeError as exc:
        fail(f"файл не является корректным JSON: {exc}")

    account = key_data.get("client_email")
    if not account:
        fail("в ключе нет поля client_email — скачан не тот тип ключа")
    print(f"     сервис-аккаунт: {account}")

    print("2/5  Идентификатор проекта")
    project = settings.gee_project or key_data.get("project_id", "")
    if not project:
        fail(
            "не задан GEE_PROJECT",
            "Укажите Project ID в .env — это идентификатор, а не отображаемое имя проекта.",
        )
    print(f"     проект: {project}")

    print("3/5  Инициализация Earth Engine")
    import ee

    try:
        credentials = ee.ServiceAccountCredentials(account, str(key_path))
        ee.Initialize(credentials, project=project)
    except Exception as exc:
        fail(
            f"не удалось инициализировать Earth Engine: {exc}",
            "Проверьте, что проект зарегистрирован в Earth Engine и включён Earth Engine API.",
        )
    print("     инициализация прошла")

    print("4/5  Поиск сцен Sentinel-2")
    geometry = ee.Geometry.Polygon([TEST_POLYGON])
    collection = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(geometry)
        .filterDate("2024-06-01", "2024-07-01")
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 40))
    )
    try:
        count = collection.size().getInfo()
    except Exception as exc:
        fail(
            f"запрос к коллекции отклонён: {exc}",
            "Чаще всего это отсутствие роли Earth Engine Resource Viewer у сервис-аккаунта.",
        )
    print(f"     найдено сцен: {count}")
    if count == 0:
        fail("сцены не найдены — доступ есть, но проверить расчёт не на чем")

    print("5/5  Расчёт среднего NDVI по полигону")
    image = collection.sort("CLOUDY_PIXEL_PERCENTAGE").first()
    ndvi = image.normalizedDifference(["B8", "B4"]).rename("ndvi")
    try:
        result = ndvi.reduceRegion(
            reducer=ee.Reducer.mean(), geometry=geometry, scale=10, maxPixels=1e9
        ).getInfo()
    except Exception as exc:
        fail(f"не удалось выполнить reduceRegion: {exc}")

    value = result.get("ndvi")
    scene_id = image.get("system:index").getInfo()
    print(f"     сцена {scene_id}: средний NDVI = {value:.4f}")

    print("\n[OK] Доступ к Google Earth Engine работает полностью.")


if __name__ == "__main__":
    main()
