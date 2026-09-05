"""Контракт HTTP-API.

Тесты описывают внешнее поведение сервиса: путь, код ответа, состав полей
и побочные эффекты в базе. Они не знают о слоях внутри и обязаны проходить
одинаково до и после перестройки внутреннего устройства — в этом их смысл.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from tests.conftest import SQUARE_POLYGON

pytestmark = pytest.mark.usefixtures("database")


# ----------------------------------------------------------------------
# Пробы
# ----------------------------------------------------------------------


def test_liveness_does_not_depend_on_external_systems(client) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_every_dependency(client) -> None:
    response = client.get("/health/ready")

    assert response.status_code in (200, 503)
    body = response.json()
    assert set(body["checks"]) == {"postgres", "s3"}
    assert body["checks"]["postgres"] is True


def test_every_response_carries_request_id(client) -> None:
    response = client.get("/health/live")

    assert response.headers["x-request-id"]


def test_request_id_from_client_is_preserved(client) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "trace-42"})

    assert response.headers["x-request-id"] == "trace-42"


# ----------------------------------------------------------------------
# Проекты
# ----------------------------------------------------------------------


def test_create_project_returns_created_resource(client, project_payload) -> None:
    response = client.post("/api/projects", json=project_payload)

    assert response.status_code == 201
    body = response.json()
    assert uuid.UUID(body["id"])
    assert body["name"] == project_payload["name"]
    assert body["period_from"] == project_payload["period_from"]
    assert body["period_to"] == project_payload["period_to"]


def test_create_project_rejects_short_period(client) -> None:
    """Период короче двух недель даёт непоказательный ряд — это правило продукта."""
    response = client.post(
        "/api/projects",
        json={
            "name": "Слишком короткий",
            "period_from": "2024-05-01",
            "period_to": "2024-05-05",
        },
    )

    assert response.status_code == 422


def test_read_missing_project_returns_stable_error_code(client) -> None:
    response = client.get(f"/api/projects/{uuid.uuid4()}")

    assert response.status_code == 404
    body = response.json()
    # Прежний контракт сохранён, к нему добавлен машиночитаемый код.
    assert body["detail"] == "проект не найден"
    assert body["error"]["code"] == "project_not_found"
    assert body["error"]["request_id"]


def test_update_project_changes_period(client, created_project) -> None:
    response = client.patch(
        f"/api/projects/{created_project['id']}",
        json={"name": "Северные поля", "period_from": "2024-05-01", "period_to": "2024-09-01"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Северные поля"
    assert body["period_from"] == "2024-05-01"
    assert body["period_to"] == "2024-09-01"


def test_update_project_rejects_short_period(client, created_project) -> None:
    """Ограничение то же, что и при создании: ряд короче двух недель бесполезен."""
    response = client.patch(
        f"/api/projects/{created_project['id']}",
        json={"period_to": created_project["period_from"]},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_period"


def test_update_missing_project_returns_404(client) -> None:
    response = client.patch(f"/api/projects/{uuid.uuid4()}", json={"name": "нет такого"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "project_not_found"


def test_delete_project_removes_its_fields(client, created_field, db_session) -> None:
    from agropulse.db.models import Field

    project_id = created_field["project_id"]

    response = client.delete(f"/api/projects/{project_id}")

    assert response.status_code == 204
    assert db_session.get(Field, uuid.UUID(created_field["id"])) is None


# ----------------------------------------------------------------------
# Поля
# ----------------------------------------------------------------------


def test_create_field_computes_area_and_returns_geojson(client, created_project) -> None:
    response = client.post(
        f"/api/projects/{created_project['id']}/fields",
        json={"name": "Поле №1", "geometry": SQUARE_POLYGON},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["geometry"]["type"] == "Polygon"
    assert 130.0 < body["area_ha"] < 150.0


def test_field_response_hides_internal_columns(client, created_field) -> None:
    """Ответ не должен раскрывать служебные поля модели хранения.

    `external_ref` в список входит намеренно: это ссылка на объект открытого
    источника, а не деталь хранения. По ней интерфейс понимает, какие контуры
    уже добавлены, и не предлагает их повторно.
    """
    assert set(created_field) == {
        "id",
        "project_id",
        "name",
        "geometry",
        "area_ha",
        "crop",
        "sowing_date",
        "source",
        "external_ref",
        "status",
        "risk_score",
        "created_at",
    }


def test_field_keeps_reference_to_open_source_contour(client, created_project) -> None:
    """Контур, выбранный из OSM, сохраняет ссылку на исходный объект."""
    response = client.post(
        f"/api/projects/{created_project['id']}/fields",
        json={
            "name": "Контур из OSM",
            "geometry": SQUARE_POLYGON,
            "source": "osm",
            "external_ref": "way/1462647786",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["source"] == "osm"
    assert body["external_ref"] == "way/1462647786"


def test_create_field_rejects_self_intersecting_polygon(client, created_project) -> None:
    bowtie = {
        "type": "Polygon",
        "coordinates": [
            [[37.60, 55.70], [37.62, 55.71], [37.62, 55.70], [37.60, 55.71], [37.60, 55.70]]
        ],
    }

    response = client.post(
        f"/api/projects/{created_project['id']}/fields",
        json={"name": "Восьмёрка", "geometry": bowtie},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_geometry"


def test_create_field_rejects_tiny_polygon(client, created_project) -> None:
    """Поле меньше нескольких пикселей Sentinel-2 не имеет смысла анализировать."""
    speck = {
        "type": "Polygon",
        "coordinates": [
            [[37.600, 55.700], [37.6001, 55.700], [37.6001, 55.7001], [37.600, 55.700]]
        ],
    }

    response = client.post(
        f"/api/projects/{created_project['id']}/fields",
        json={"name": "Пятнышко", "geometry": speck},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_geometry"


def test_create_field_in_missing_project_returns_404(client) -> None:
    response = client.post(
        f"/api/projects/{uuid.uuid4()}/fields",
        json={"name": "Поле", "geometry": SQUARE_POLYGON},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "project_not_found"


def test_update_field_name_keeps_collected_data(client, analyzed_field, db_session) -> None:
    from agropulse.db.models import Observation

    field_id = analyzed_field["id"]

    response = client.patch(f"/api/fields/{field_id}", json={"name": "Новое имя"})

    assert response.status_code == 200
    assert response.json()["name"] == "Новое имя"
    remaining = db_session.query(Observation).filter_by(field_id=uuid.UUID(field_id)).count()
    assert remaining > 0


def test_changing_geometry_drops_all_derived_data(
    client, analyzed_field, db_session
) -> None:
    """Новый контур — другая область: прежние выводы к ней не относятся."""
    from agropulse.db.models import Anomaly, Field, ForecastRun, Observation

    field_id = uuid.UUID(analyzed_field["id"])
    moved = {
        "type": "Polygon",
        "coordinates": [
            [[38.60, 54.70], [38.62, 54.70], [38.62, 54.71], [38.60, 54.71], [38.60, 54.70]]
        ],
    }

    response = client.patch(f"/api/fields/{field_id}", json={"geometry": moved})

    assert response.status_code == 200
    assert db_session.query(Observation).filter_by(field_id=field_id).count() == 0
    assert db_session.query(Anomaly).filter_by(field_id=field_id).count() == 0
    assert db_session.query(ForecastRun).filter_by(field_id=field_id).count() == 0

    field = db_session.get(Field, field_id)
    db_session.refresh(field)
    assert field.status.value == "pending"
    assert field.risk_score is None


def test_timeseries_reports_origin_of_every_point(client, analyzed_field) -> None:
    response = client.get(f"/api/fields/{analyzed_field['id']}/timeseries")

    assert response.status_code == 200
    body = response.json()
    origins = {point["value_type"] for point in body["observations"]}
    assert origins == {"observed", "restored", "forecast"}
    assert body["stats"]["observed"] == 8
    assert body["stats"]["restored"] == 1
    assert body["stats"]["forecast"] == 1


def test_timeseries_of_missing_field_returns_404(client) -> None:
    response = client.get(f"/api/fields/{uuid.uuid4()}/timeseries")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "field_not_found"


# ----------------------------------------------------------------------
# Запуск обработки
# ----------------------------------------------------------------------


def test_start_processing_publishes_task(client, created_field, published_tasks) -> None:
    response = client.post(f"/api/fields/{created_field['id']}/process")

    assert response.status_code == 202
    body = response.json()
    assert body["field_id"] == created_field["id"]
    assert body["task_id"]

    # В задачу уходит только идентификатор: воркер читает данные сам.
    assert published_tasks == [
        ("agropulse.tasks.pipeline.process_field", (created_field["id"],))
    ]


def test_start_project_processing_publishes_task_per_field(
    client, created_project, created_field, published_tasks
) -> None:
    response = client.post(f"/api/projects/{created_project['id']}/process")

    assert response.status_code == 202
    assert len(response.json()["tasks"]) == 1
    assert len(published_tasks) == 1


def test_project_without_fields_cannot_be_processed(client, created_project) -> None:
    response = client.post(f"/api/projects/{created_project['id']}/process")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "project_has_no_fields"


# ----------------------------------------------------------------------
# Результаты анализа
# ----------------------------------------------------------------------


def test_anomalies_are_returned_worst_first(client, analyzed_field) -> None:
    response = client.get(f"/api/fields/{analyzed_field['id']}/anomalies")

    assert response.status_code == 200
    anomalies = response.json()
    assert len(anomalies) == 1
    assert anomalies[0]["severity"] == "critical"
    assert anomalies[0]["max_zscore"] == -2.4


def test_risk_exposes_factor_breakdown(client, analyzed_field) -> None:
    response = client.get(f"/api/fields/{analyzed_field['id']}/risk")

    assert response.status_code == 200
    body = response.json()
    assert body["score"] == 72.5
    assert body["status"] == "critical"
    assert body["breakdown"]["anomaly_severity"] == 24.0
    assert body["explanation"]
    assert body["climatology"]["available"] is True


def test_forecast_exposes_direction_and_confidence(client, analyzed_field) -> None:
    response = client.get(f"/api/fields/{analyzed_field['id']}/forecast")

    assert response.status_code == 200
    body = response.json()
    assert body["direction"] == "declining"
    assert body["risk_level"] == "high"
    assert body["confidence"] == 0.6
    assert body["horizon_days"] == 14


def test_forecast_is_null_until_field_is_analyzed(client, created_field) -> None:
    """Отсутствие прогноза — состояние, а не ошибка ресурса."""
    response = client.get(f"/api/fields/{created_field['id']}/forecast")

    assert response.status_code == 200
    assert response.json() is None


def test_forecast_of_missing_field_returns_404(client) -> None:
    response = client.get(f"/api/fields/{uuid.uuid4()}/forecast")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "field_not_found"


def test_summary_ranks_fields_by_risk(client, analyzed_field, created_project) -> None:
    response = client.get(f"/api/projects/{created_project['id']}/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["total_fields"] == 1
    assert body["critical"] == 1
    field = body["fields"][0]
    assert field["inspection_rank"] == 1
    assert field["anomalies_count"] == 1
    assert field["worst_anomaly"]["max_zscore"] == -2.4
    assert field["observed_points"] == 8
    assert field["restored_points"] == 1


def test_field_without_risk_gets_no_inspection_rank(
    client, created_project, created_field
) -> None:
    """Выдуманный балл хуже честного «данных не хватает»."""
    response = client.get(f"/api/projects/{created_project['id']}/summary")

    field = response.json()["fields"][0]
    assert field["risk_score"] is None
    assert field["inspection_rank"] is None


# ----------------------------------------------------------------------
# Выгрузки
# ----------------------------------------------------------------------


def test_field_csv_contains_every_point_with_its_origin(client, analyzed_field) -> None:
    response = client.get(f"/api/fields/{analyzed_field['id']}/export.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")

    text = response.text.lstrip("﻿")
    lines = [line for line in text.splitlines() if line]
    header = lines[0].split(",")
    assert header[:6] == [
        "field_id",
        "field_name",
        "date",
        "ndvi_mean",
        "ndmi_mean",
        "value_type",
    ]
    assert len(lines) == 1 + 10


def test_csv_marks_dates_inside_anomaly_period(client, analyzed_field) -> None:
    response = client.get(f"/api/fields/{analyzed_field['id']}/export.csv")

    rows = [line.split(",") for line in response.text.lstrip("﻿").splitlines() if line]
    levels = {row[2]: row[11] for row in rows[1:]}
    assert levels[date(2024, 5, 16).isoformat()] == "critical"
    assert levels[date(2024, 5, 1).isoformat()] == ""


def test_project_csv_of_missing_project_returns_404(client) -> None:
    response = client.get(f"/api/projects/{uuid.uuid4()}/export.csv")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "project_not_found"


# ----------------------------------------------------------------------
# Поток событий
# ----------------------------------------------------------------------


def test_events_of_missing_project_returns_404(client) -> None:
    response = client.get(f"/api/projects/{uuid.uuid4()}/events")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "project_not_found"


def test_unknown_route_also_carries_error_code(client) -> None:
    response = client.get("/api/unknown")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "http_404"
