"""Конфигурация сервиса.

Все настройки читаются только из переменных окружения — ни одного значения,
зашитого в образ. Это требование продиктовано запуском в Kubernetes: один и тот же
образ должен работать в docker compose и в кластере, отличаясь лишь ConfigMap/Secret.

Настройки собираются один раз за процесс (`get_settings`) и передаются
компонентам, а не читаются каждым модулем через `os.getenv`.

Секреты объявлены как `SecretStr`: их значение не попадёт ни в `repr`
настроек, ни в traceback, ни в лог, куда объект настроек занесли по ошибке.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PositiveFloat, PositiveInt, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Значения по умолчанию, пригодные только для локальной разработки. Вынесены
# в константы, чтобы проверка на старте могла их распознать и не дать
# развернуть сервис с ними в dev- или prod-окружении.
DEV_PASSWORD = "agropulse"
LOCAL_ENVIRONMENTS = ("local", "test")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- общее ---
    app_env: Literal["local", "test", "dev", "prod"] = "local"
    log_level: str = "INFO"
    log_json: bool = False
    """Формат логов. В кластере включается, чтобы записи разбирал сборщик логов."""

    api_prefix: str = "/api"
    cors_allow_origins: list[str] = Field(default_factory=list)
    """Разрешённые origin. В `local` подставляется `*`, см. `resolved_cors_origins`."""

    session_cookie_secure: bool = False
    """Ставить ли на cookie посетителя флаг Secure.

    По умолчанию выключен: локальный запуск идёт по http, и браузер просто
    не сохранил бы такую куку — пользователь терял бы свои проекты при каждом
    заходе. За TLS-терминатором в кластере включается через окружение.
    """

    # --- база данных ---
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "agropulse"
    postgres_user: str = "agropulse"
    postgres_password: SecretStr = SecretStr(DEV_PASSWORD)

    database_pool_size: PositiveInt = 5
    database_max_overflow: PositiveInt = 10

    # Производные адреса объявлены обычными свойствами, а не `computed_field`.
    # Разница существенная: computed_field попадает в `repr` и в `model_dump`,
    # а DSN содержит пароль — и тогда `SecretStr` защищает пароль, но не строку
    # подключения, собранную из него.
    @property
    def database_url(self) -> str:
        """DSN для SQLAlchemy. Драйвер psycopg3, синхронный."""
        return (
            f"postgresql+psycopg://{self.postgres_user}:"
            f"{self.postgres_password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # --- Redis: брокер Celery, кэш внешних API и pub/sub прогресса ---
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db_broker: int = 0
    redis_db_cache: int = 1
    redis_socket_timeout_seconds: PositiveFloat = 2.0

    @property
    def celery_broker_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db_broker}"

    @property
    def redis_cache_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db_cache}"

    celery_result_backend_url: str = ""
    """Хранилище результатов Celery. Пусто — используется брокер."""

    @property
    def celery_result_backend(self) -> str:
        return self.celery_result_backend_url or self.celery_broker_url

    @property
    def cache_namespace(self) -> str:
        """Пространство имён ключей кэша.

        Окружение входит в префикс, чтобы стенды, случайно нацеленные на один
        Redis, не читали чужие ответы. Версия — чтобы смена формата значения
        не требовала ручной чистки: старые ключи просто перестают находиться.
        """
        return f"agropulse:{self.app_env}:cache:v1"

    # --- хранилище артефактов (MinIO / S3) ---
    # Локальный диск не используется сознательно: поды api и worker должны
    # оставаться stateless, иначе несколько реплик в k8s разъедутся по данным.
    s3_endpoint_url: str = "http://minio:9000"
    s3_access_key: str = "agropulse"
    s3_secret_key: SecretStr = SecretStr(DEV_PASSWORD)
    s3_bucket: str = "agropulse"
    s3_region: str = "us-east-1"
    s3_public_base_url: str = ""  # если пусто — отдаём presigned-ссылки
    s3_url_expires_seconds: PositiveInt = 3600

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
    http_timeout_seconds: PositiveFloat = 60.0

    # --- сервис ML-моделей (восстановление пропусков, прогноз) ---
    ml_service_url: str = "http://ml-service:8000"
    ml_service_timeout_seconds: PositiveFloat = 120.0
    ml_health_timeout_seconds: PositiveFloat = 3.0
    """Проверка живости сервиса моделей. Намеренно короткая: при отсутствующем
    сервисе обработка каждого поля не должна ждать полный таймаут запроса."""

    ml_use_dev_stub: bool = True
    """Разрешить временную заглушку вместо сервиса моделей.

    ВРЕМЕННО, ПОДЛЕЖИТ УДАЛЕНИЮ. Нужна только чтобы разработка остальной части
    сервиса не простаивала, пока сервис моделей не готов. Это не резервный
    механизм: в готовом решении отсутствие сервиса моделей должно быть ошибкой,
    а не поводом подставить приближение по соседним точкам.
    """

    # --- LLM через OpenRouter ---
    openrouter_api_key: SecretStr = SecretStr("")
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = ""
    openrouter_timeout_seconds: PositiveFloat = 120.0
    llm_enabled: bool = True

    # --- параметры анализа ---
    history_seasons: int = Field(default=4, ge=1, le=10)
    """Сколько предыдущих сезонов подгружать для построения климатической нормы."""

    forecast_horizon_days: int = Field(default=14, ge=1, le=30)

    # --- Celery ---
    collect_soft_time_limit_seconds: PositiveInt = 900
    collect_time_limit_seconds: PositiveInt = 1200
    analyze_soft_time_limit_seconds: PositiveInt = 300
    analyze_time_limit_seconds: PositiveInt = 420
    task_max_retries: int = Field(default=3, ge=0, le=10)

    # ------------------------------------------------------------------

    @property
    def is_local(self) -> bool:
        return self.app_env in LOCAL_ENVIRONMENTS

    @property
    def resolved_cors_origins(self) -> list[str]:
        """Origin для CORS.

        В разработке фронтенд поднимается отдельным origin (Vite на 5173).
        В кластере api и web стоят за одним Ingress, и CORS не задействован,
        поэтому пустой список — правильное значение по умолчанию.
        """
        if self.cors_allow_origins:
            return self.cors_allow_origins
        return ["*"] if self.app_env == "local" else []

    @model_validator(mode="after")
    def forbid_development_secrets_outside_local(self) -> "Settings":
        """Не дать развернуть сервис с паролями из примера конфигурации.

        Проверка выполняется при сборке настроек, то есть на старте процесса:
        сервис с небезопасной конфигурацией не должен подняться и молча начать
        принимать трафик.
        """
        if self.is_local:
            return self

        insecure = [
            name
            for name, value in (
                ("POSTGRES_PASSWORD", self.postgres_password),
                ("S3_SECRET_KEY", self.s3_secret_key),
            )
            if value.get_secret_value() in ("", DEV_PASSWORD)
        ]
        if insecure:
            raise ValueError(
                f"в окружении {self.app_env} заданы значения по умолчанию: "
                f"{', '.join(insecure)}"
            )
        return self

    @model_validator(mode="after")
    def check_time_limits_order(self) -> "Settings":
        """Жёсткий предел должен быть позже мягкого.

        Иначе задача снимается раньше, чем получает шанс завершиться штатно
        по `SoftTimeLimitExceeded`, и конечный статус ошибки записать некому.
        """
        pairs = (
            ("collect", self.collect_soft_time_limit_seconds, self.collect_time_limit_seconds),
            ("analyze", self.analyze_soft_time_limit_seconds, self.analyze_time_limit_seconds),
        )
        for name, soft, hard in pairs:
            if hard <= soft:
                raise ValueError(
                    f"{name}: жёсткий предел времени ({hard} с) должен быть больше "
                    f"мягкого ({soft} с)"
                )
        return self


@lru_cache
def get_settings() -> Settings:
    """Настройки читаются один раз за жизнь процесса."""
    return Settings()
