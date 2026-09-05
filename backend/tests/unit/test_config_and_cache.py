"""Конфигурация и кэш внешних источников."""

from __future__ import annotations

import pytest
from agropulse.config import DEV_PASSWORD, Settings
from pydantic import ValidationError


def _settings(**overrides) -> Settings:
    base = {
        "app_env": "local",
        "postgres_password": "s3cret",
        "s3_secret_key": "s3cret",
    }
    return Settings(**{**base, **overrides})


def test_secrets_are_hidden_in_repr() -> None:
    """Объект настроек не должен раскрывать пароль, попав в лог по ошибке."""
    settings = _settings(postgres_password="very-secret-value")

    assert "very-secret-value" not in repr(settings)
    assert settings.postgres_password.get_secret_value() == "very-secret-value"


def test_database_url_is_assembled_from_parts() -> None:
    settings = _settings(
        postgres_host="db", postgres_port=6432, postgres_db="agro", postgres_user="u"
    )

    assert settings.database_url.startswith("postgresql+psycopg://u:")
    assert settings.database_url.endswith("@db:6432/agro")


def test_broker_and_cache_live_in_separate_redis_databases() -> None:
    """Вытеснение ключей кэша не должно затрагивать очередь задач."""
    settings = _settings()

    assert settings.celery_broker_url.endswith("/0")
    assert settings.redis_cache_url.endswith("/1")


def test_development_password_is_refused_outside_local() -> None:
    """Сервис с паролем из примера конфигурации не должен подняться."""
    with pytest.raises(ValidationError, match="POSTGRES_PASSWORD"):
        Settings(app_env="prod", postgres_password=DEV_PASSWORD, s3_secret_key="ok")


def test_development_password_is_allowed_locally() -> None:
    settings = Settings(app_env="local", postgres_password=DEV_PASSWORD)

    assert settings.is_local is True


def test_hard_time_limit_must_exceed_soft_one() -> None:
    """Иначе задача снимается раньше, чем успеет записать конечный статус."""
    with pytest.raises(ValidationError, match="жёсткий предел"):
        _settings(collect_soft_time_limit_seconds=900, collect_time_limit_seconds=900)


def test_cors_is_open_only_locally() -> None:
    assert _settings(app_env="local").resolved_cors_origins == ["*"]
    assert _settings(app_env="prod").resolved_cors_origins == []
    assert _settings(app_env="prod", cors_allow_origins=["https://agro"]).resolved_cors_origins == [
        "https://agro"
    ]


def test_cache_namespace_separates_environments() -> None:
    """Стенды, случайно нацеленные на один Redis, не читают чужие ответы."""
    assert _settings(app_env="local").cache_namespace != _settings(
        app_env="prod"
    ).cache_namespace


# ----------------------------------------------------------------------


def test_cache_key_ignores_argument_order() -> None:
    from agropulse.providers import cache

    first = cache.make_key("open_meteo", latitude=55.7, longitude=37.6)
    second = cache.make_key("open_meteo", longitude=37.6, latitude=55.7)

    assert first == second
    assert first.startswith("agropulse:")


def test_cache_key_depends_on_parameters() -> None:
    from agropulse.providers import cache

    assert cache.make_key("open_meteo", latitude=55.7) != cache.make_key(
        "open_meteo", latitude=55.8
    )


def test_cache_failure_does_not_break_the_call(monkeypatch) -> None:
    """Кэш — оптимизация, а не источник истины: его отказ не должен
    превращаться в отказ обработки поля."""
    from agropulse.providers import cache

    monkeypatch.setattr(cache, "get_redis", lambda: None)
    monkeypatch.setattr(cache, "get", lambda key: None)
    monkeypatch.setattr(cache, "set", lambda *args, **kwargs: None)

    calls = []

    def loader():
        calls.append(1)
        return {"value": 1}

    assert cache.cached_call("provider", 60, loader, param=1) == {"value": 1}
    assert calls == [1]
