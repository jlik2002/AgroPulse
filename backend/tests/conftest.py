"""Общая обвязка тестов.

Тесты делятся на две группы. Модульные проверяют расчёты и не требуют
инфраструктуры. Интеграционные работают с настоящим PostgreSQL: тип `Geometry`
из PostGIS невозможно подменить SQLite, а проверять API на выдуманном хранилище
означало бы проверять не то, что работает в эксплуатации.

Отдельная база создаётся на время сессии и накатывается миграциями. Это
одновременно проверяет требование гайда «миграции применяются на пустой БД».
Если PostgreSQL недоступен, интеграционные тесты пропускаются, а модульные
продолжают работать.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent

# База переключается до первого обращения к настройкам: `get_settings`
# кэширует результат на весь процесс.
TEST_DATABASE_SUFFIX = "_test"
os.environ.setdefault("APP_ENV", "test")
os.environ["POSTGRES_DB"] = (
    os.environ.get("POSTGRES_DB", "agropulse") + TEST_DATABASE_SUFFIX
)

from agropulse.config import get_settings  # noqa: E402


def _admin_url() -> str:
    """DSN к служебной базе: из неё создаётся и удаляётся тестовая."""
    settings = get_settings()
    # get_secret_value обязателен: сам по себе SecretStr печатается звёздочками,
    # и DSN получился бы синтаксически верным, но с неправильным паролем.
    password = settings.postgres_password.get_secret_value()
    return (
        f"postgresql+psycopg://{settings.postgres_user}:{password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/postgres"
    )


@pytest.fixture(scope="session")
def database() -> Iterator[None]:
    """Создать тестовую базу, накатить миграции, убрать за собой."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import OperationalError

    settings = get_settings()
    admin = create_engine(_admin_url(), isolation_level="AUTOCOMMIT", pool_pre_ping=True)

    try:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{settings.postgres_db}"'))
            connection.execute(text(f'CREATE DATABASE "{settings.postgres_db}"'))
    except OperationalError as exc:
        pytest.skip(f"PostgreSQL недоступен, интеграционные тесты пропущены: {exc}")

    from alembic import command
    from alembic.config import Config

    alembic_config = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(alembic_config, "head")

    yield

    from agropulse.db.session import dispose_engine

    dispose_engine()
    with admin.connect() as connection:
        connection.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :name AND pid <> pg_backend_pid()"
            ),
            {"name": settings.postgres_db},
        )
        connection.execute(text(f'DROP DATABASE IF EXISTS "{settings.postgres_db}"'))
    admin.dispose()


@pytest.fixture
def db_session(database) -> Iterator[Session]:  # noqa: F821
    """Сессия для проверки побочных эффектов, с очисткой данных после теста."""
    from agropulse.db.session import create_session
    from sqlalchemy import text

    session = create_session()
    try:
        yield session
    finally:
        session.rollback()
        # Порядок не важен: TRUNCATE ... CASCADE снимает внешние ключи.
        session.execute(
            text(
                "TRUNCATE projects, fields, observations, anomalies, "
                "forecast_runs, jobs, scene_assets, raw_cache CASCADE"
            )
        )
        session.commit()
        session.close()


@pytest.fixture
def published_tasks(monkeypatch) -> list[tuple[str, tuple]]:
    """Перехват публикации Celery-задач.

    Тест обязан видеть, что задача поставлена в очередь, но не должен зависеть
    от живого брокера. Подменяется сам объект задачи, поэтому перехват работает
    независимо от того, какой слой её публикует.
    """
    from agropulse.tasks import pipeline

    published: list[tuple[str, tuple]] = []

    class _Result:
        def __init__(self, task_id: str) -> None:
            self.id = task_id

    def _record(name: str):
        def _delay(*args, **kwargs):
            published.append((name, args))
            return _Result(str(uuid.uuid4()))

        return _delay

    for task in (pipeline.collect_field_data, pipeline.analyze_field, pipeline.process_field):
        monkeypatch.setattr(task, "delay", _record(task.name))

    return published


@pytest.fixture
def client(database, published_tasks) -> Iterator[TestClient]:  # noqa: F821
    """HTTP-клиент поверх приложения с тестовой базой."""
    from agropulse.db.session import create_session
    from agropulse.main import create_app
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client

    session = create_session()
    session.execute(
        text(
            "TRUNCATE projects, fields, observations, anomalies, "
            "forecast_runs, jobs, scene_assets, raw_cache CASCADE"
        )
    )
    session.commit()
    session.close()


# ----------------------------------------------------------------------
# Данные для тестов
# ----------------------------------------------------------------------

# Квадрат примерно 1.1 × 1.1 км в средней полосе — правдоподобное поле около 120 га.
SQUARE_POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [
            [37.60, 55.70],
            [37.62, 55.70],
            [37.62, 55.71],
            [37.60, 55.71],
            [37.60, 55.70],
        ]
    ],
}


@pytest.fixture
def project_payload() -> dict:
    return {
        "name": "Тестовое хозяйство",
        "period_from": date(2024, 5, 1).isoformat(),
        "period_to": date(2024, 8, 31).isoformat(),
    }


@pytest.fixture
def created_project(client, project_payload) -> dict:
    response = client.post("/api/projects", json=project_payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def created_field(client, created_project) -> dict:
    response = client.post(
        f"/api/projects/{created_project['id']}/fields",
        json={
            "name": "Поле №1",
            "geometry": SQUARE_POLYGON,
            "crop": "пшеница",
            "sowing_date": date(2024, 4, 20).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def analyzed_field(client, created_field, db_session) -> dict:
    """Поле с готовыми результатами анализа.

    Данные записываются напрямую: тесты выгрузок и сводки проверяют чтение,
    а не пайплайн, и не должны зависеть от внешних источников.
    """
    from agropulse.db.models import (
        Anomaly,
        AnomalySeverity,
        Field,
        FieldStatus,
        ForecastRun,
        Observation,
        ValueType,
    )

    field_id = uuid.UUID(created_field["id"])
    start = date(2024, 5, 1)

    for offset in range(0, 40, 5):
        day = start + timedelta(days=offset)
        db_session.add(
            Observation(
                field_id=field_id,
                date=day,
                value_type=ValueType.OBSERVED,
                source="s2_gee",
                ndvi_mean=0.7 - offset * 0.01,
                ndmi_mean=0.3,
                valid_fraction=0.9,
                cloud_fraction=0.05,
                temperature=21.5,
                precipitation=1.2,
                ndvi_zscore=-1.4,
            )
        )
    db_session.add(
        Observation(
            field_id=field_id,
            date=start + timedelta(days=2),
            value_type=ValueType.RESTORED,
            source="dev_stub",
            ndvi_mean=0.68,
            confidence=0.8,
        )
    )
    db_session.add(
        Observation(
            field_id=field_id,
            date=start + timedelta(days=45),
            value_type=ValueType.FORECAST,
            source="dev_stub",
            ndvi_mean=0.5,
            ndvi_lo=0.42,
            ndvi_hi=0.58,
            confidence=0.6,
        )
    )
    db_session.add(
        Anomaly(
            field_id=field_id,
            start_date=start + timedelta(days=10),
            end_date=start + timedelta(days=25),
            duration_days=16,
            severity=AnomalySeverity.CRITICAL,
            max_zscore=-2.4,
            mean_zscore=-1.8,
            restored_fraction=0.2,
            trust="confirmed",
            factors={
                "hypotheses": ["сухо и жарко"],
                "ndmi_trend": -0.06,
                "trust": {
                    "level": "confirmed",
                    "optical": "strong",
                    "radar": "agrees",
                    "observations": 4,
                    "reasons": [
                        "событие измерено: пригодных снимка в окне 4",
                        "радар независимо показывает то же самое",
                    ],
                },
            },
        )
    )
    db_session.add(
        ForecastRun(
            field_id=field_id,
            horizon_days=14,
            model_version="dev_stub",
            direction="declining",
            risk_level="high",
            confidence=0.6,
        )
    )

    field = db_session.get(Field, field_id)
    field.status = FieldStatus.CRITICAL
    field.risk_score = 72.5
    field.risk_breakdown = {
        "score": 72.5,
        "weights": {"anomaly_severity": 24.0, "anomaly_duration": 10.7},
        "explanation": ["максимальное отклонение от нормы z=-2.40"],
        "confidence": 0.66,
        "insufficient_reason": None,
        "climatology": {"available": True, "seasons_used": 4},
    }
    field.data_quality = {"satellite_source": "s2_gee", "scenes_total": 8, "scenes_usable": 8}
    db_session.commit()

    return created_field
