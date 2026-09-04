"""Конфигурация сервиса.

Все настройки читаются только из переменных окружения — ни одного значения,
зашитого в образ. Это требование продиктовано запуском в Kubernetes: один и тот же
образ должен работать в docker compose и в кластере, отличаясь лишь ConfigMap/Secret.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- общее ---
    app_env: Literal["local", "dev", "prod"] = "local"
    log_level: str = "INFO"
    api_prefix: str = "/api"

    # --- база данных ---
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "agropulse"
    postgres_user: str = "agropulse"
    postgres_password: str = "agropulse"

    @computed_field
    @property
    def database_url(self) -> str:
        """DSN для SQLAlchemy. Драйвер psycopg3, синхронный."""
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # --- Redis: брокер Celery, кэш внешних API и pub/sub прогресса ---
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db_broker: int = 0
    redis_db_cache: int = 1

    @computed_field
    @property
    def celery_broker_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db_broker}"

    @computed_field
    @property
    def redis_cache_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db_cache}"

    # --- хранилище артефактов (MinIO / S3) ---
    # Локальный диск не используется сознательно: поды api и worker должны
    # оставаться stateless, иначе несколько реплик в k8s разъедутся по данным.
    s3_endpoint_url: str = "http://minio:9000"
    s3_access_key: str = "agropulse"
    s3_secret_key: str = "agropulse"
    s3_bucket: str = "agropulse"
    s3_region: str = "us-east-1"
    s3_public_base_url: str = ""  # если пусто — отдаём presigned-ссылки

    # --- Google Earth Engine ---
    # Путь к JSON сервис-аккаунта. В k8s монтируется из Secret, в compose — из bind-mount.
    gee_service_account_file: str = "/run/secrets/gee-service-account.json"
    gee_project: str = ""

    # --- внешние открытые источники ---
    open_meteo_archive_url: str = "https://archive-api.open-meteo.com/v1/archive"
    open_meteo_forecast_url: str = "https://api.open-meteo.com/v1/forecast"
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    nominatim_url: str = "https://nominatim.openstreetmap.org/search"
    # Nominatim требует осмысленный User-Agent, иначе банит по политике использования.
    http_user_agent: str = "AgroPulse/0.1 (hackathon prototype)"
    http_timeout_seconds: float = 60.0

    # --- сервис ML-моделей (восстановление пропусков, прогноз) ---
    ml_service_url: str = "http://ml-service:8000"
    ml_service_timeout_seconds: float = 120.0
    # Если сервис недоступен, пайплайн не падает, а переключается на локальный baseline.
    ml_fallback_to_baseline: bool = True

    # --- LLM через OpenRouter ---
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = ""
    llm_enabled: bool = True

    # --- параметры анализа ---
    history_seasons: int = Field(default=4, ge=1, le=10)
    """Сколько предыдущих сезонов подгружать для построения климатической нормы."""

    forecast_horizon_days: int = 14


@lru_cache
def get_settings() -> Settings:
    """Настройки читаются один раз за жизнь процесса."""
    return Settings()
