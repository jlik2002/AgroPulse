"""Модели данных AgroPulse.

Центральная сущность — поле (`Field`). У каждого поля собственный контур, история
наблюдений, аномалии и оценка риска; расчёты выполняются отдельно для каждого поля,
а проект (`Project`) лишь группирует их общим периодом анализа.

Ключевое ограничение схемы — уникальность наблюдения по
(field_id, date, value_type, source). Оно нужно не для чистоты данных, а для
идемпотентности: Celery настроен на `task_acks_late`, поэтому при рестарте воркера
задача сбора выполнится повторно, и запись должна пройти как upsert, а не как дубль.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


# --------------------------------------------------------------------------
# Перечисления
# --------------------------------------------------------------------------
# native_enum=False: перечисления хранятся как VARCHAR с CHECK-ограничением.
# Нативные типы PostgreSQL пришлось бы менять отдельными миграциями при каждом
# добавлении значения, что на коротком проекте только мешает.


class ValueType(str, enum.Enum):
    """Происхождение значения ряда. Продуктовый принцип: факты отделены от расчётов."""

    OBSERVED = "observed"    # рассчитано по пригодному снимку
    RESTORED = "restored"    # восстановлено моделью внутри исторического ряда
    FORECAST = "forecast"    # относится к будущему горизонту прогноза


class FieldStatus(str, enum.Enum):
    CRITICAL = "critical"                    # рекомендуется первоочередной осмотр
    ATTENTION = "attention"                  # наблюдение или плановая проверка
    NORMAL = "normal"                        # аномалий не обнаружено
    INSUFFICIENT_DATA = "insufficient_data"  # искусственный риск не выставляем
    PENDING = "pending"                      # ещё не обрабатывалось
    FAILED = "failed"


class FieldSource(str, enum.Enum):
    """Откуда взялся контур поля."""

    DRAWN = "drawn"              # нарисован пользователем вручную
    OSM = "osm"                  # готовый контур из OpenStreetMap
    WORLDCEREAL = "worldcereal"  # контур из ESA WorldCereal


class AnomalySeverity(str, enum.Enum):
    # Пороги z-score взяты из постановки задачи: -2 <= z < -1 и z < -2.
    MODERATE = "moderate"  # угнетение биомассы
    CRITICAL = "critical"  # критическая аномалия


class PipelineStage(str, enum.Enum):
    """Девять стадий обработки. Ровно в этом порядке показываются пользователю."""

    SEARCH_SCENES = "search_scenes"        # поиск спутниковых сцен
    CLOUD_MASKING = "cloud_masking"        # фильтрация облаков и теней
    INDICES = "indices"                    # расчёт индексов
    WEATHER = "weather"                    # получение погоды
    TIMESERIES = "timeseries"              # построение временного ряда
    GAP_FILLING = "gap_filling"            # восстановление пропусков
    ANOMALIES = "anomalies"                # поиск аномалий
    RISK_FORECAST = "risk_forecast"        # расчёт риска и прогноза
    VISUALIZATION = "visualization"        # подготовка визуализаций


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class AssetKind(str, enum.Enum):
    RGB = "rgb"
    NDVI = "ndvi"
    NDMI = "ndmi"


def _enum(py_enum: type[enum.Enum], name: str) -> Enum:
    return Enum(
        py_enum,
        name=name,
        native_enum=False,
        values_callable=lambda enum: [member.value for member in enum],
    )


# --------------------------------------------------------------------------
# Проект и поле
# --------------------------------------------------------------------------


class Project(Base):
    """Анонимное рабочее пространство без регистрации.

    Общий период анализа хранится на проекте, чтобы поля были сопоставимы
    при групповом сравнении и ранжировании.
    """

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str | None] = mapped_column(String(200))
    period_from: Mapped[date] = mapped_column(Date, nullable=False)
    period_to: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    fields: Mapped[list[Field]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("period_to >= period_from", name="ck_projects_period_order"),
    )


class Field(Base):
    """Отдельное поле — центральный объект продукта."""

    __tablename__ = "fields"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    # SRID 4326 — географические координаты, в них приходят и OSM, и рисунок пользователя.
    # Площадь считаем через ST_Area(geography), а не в градусах.
    geom: Mapped[object] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=4326, spatial_index=True), nullable=False
    )
    area_ha: Mapped[float | None] = mapped_column(Float)

    # Культура и дата посева необязательны: без них выполняется общий анализ
    # динамики, а культурно-специфичная интерпретация помечается недоступной.
    crop: Mapped[str | None] = mapped_column(String(100))
    sowing_date: Mapped[date | None] = mapped_column(Date)

    source: Mapped[FieldSource] = mapped_column(
        _enum(FieldSource, "field_source"), default=FieldSource.DRAWN
    )
    external_ref: Mapped[str | None] = mapped_column(String(100))  # id объекта OSM

    status: Mapped[FieldStatus] = mapped_column(
        _enum(FieldStatus, "field_status"), default=FieldStatus.PENDING, index=True
    )
    risk_score: Mapped[float | None] = mapped_column(Float)
    # Вклад отдельных факторов в составной риск — показывается пользователю,
    # поэтому храним разложение, а не только итоговый балл.
    risk_breakdown: Mapped[dict | None] = mapped_column(JSONB)
    data_quality: Mapped[dict | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped[Project] = relationship(back_populates="fields")
    observations: Mapped[list[Observation]] = relationship(
        back_populates="field", cascade="all, delete-orphan"
    )
    anomalies: Mapped[list[Anomaly]] = relationship(
        back_populates="field", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Площадь проверяется при создании поля, но проверка в Python защищает
        # только один путь записи. Данные приходят ещё и из batch-сценариев,
        # поэтому инвариант закреплён в базе.
        CheckConstraint("area_ha IS NULL OR area_ha > 0", name="ck_fields_area_positive"),
    )


# --------------------------------------------------------------------------
# Наблюдения
# --------------------------------------------------------------------------


class Observation(Base):
    """Одна дата для одного поля.

    Прогнозные точки лежат здесь же с value_type='forecast' — так выгрузка CSV
    и построение графика делаются одним запросом, а не склейкой двух таблиц.
    """

    __tablename__ = "observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    field_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fields.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)

    value_type: Mapped[ValueType] = mapped_column(_enum(ValueType, "value_type"), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)  # s2_gee, s2_stac, ml, baseline

    # Индексы вегетации и влажности
    ndvi_mean: Mapped[float | None] = mapped_column(Float)
    ndmi_mean: Mapped[float | None] = mapped_column(Float)
    evi_mean: Mapped[float | None] = mapped_column(Float)

    # Качество наблюдения
    valid_fraction: Mapped[float | None] = mapped_column(Float)
    cloud_fraction: Mapped[float | None] = mapped_column(Float)
    scene_id: Mapped[str | None] = mapped_column(String(200))

    # Погодный контекст на ту же дату
    temperature: Mapped[float | None] = mapped_column(Float)
    precipitation: Mapped[float | None] = mapped_column(Float)

    # Отклонение от климатической нормы поля
    ndvi_zscore: Mapped[float | None] = mapped_column(Float)

    # Доверительный интервал — заполняется только для прогнозных точек
    ndvi_lo: Mapped[float | None] = mapped_column(Float)
    ndvi_hi: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)

    missing_reason: Mapped[str | None] = mapped_column(String(200))
    raw: Mapped[dict | None] = mapped_column(JSONB)

    field: Mapped[Field] = relationship(back_populates="observations")

    __table_args__ = (
        # Ключ идемпотентности: повторный прогон задачи обновляет строку, а не дублирует её.
        UniqueConstraint(
            "field_id", "date", "value_type", "source", name="uq_observation_identity"
        ),
        Index("ix_observations_field_date", "field_id", "date"),
        # Анализ и отчёты почти всегда выбирают ряд одного типа значений
        # (только наблюдения, только прогноз). Индекс закрывает такую выборку
        # целиком, не заставляя базу отбрасывать лишние строки после чтения.
        Index("ix_observations_field_type_date", "field_id", "value_type", "date"),
        # Нормированная разность по определению лежит в [-1, 1]. Значение вне
        # диапазона означает ошибку расчёта, и обнаружить её лучше при записи,
        # чем на графике у пользователя. EVI не ограничиваем: его формула
        # со свободным членом допускает выход за эти пределы.
        CheckConstraint(
            "(ndvi_mean IS NULL OR ndvi_mean BETWEEN -1 AND 1) "
            "AND (ndmi_mean IS NULL OR ndmi_mean BETWEEN -1 AND 1)",
            name="ck_observations_index_range",
        ),
        CheckConstraint(
            "(valid_fraction IS NULL OR valid_fraction BETWEEN 0 AND 1) "
            "AND (cloud_fraction IS NULL OR cloud_fraction BETWEEN 0 AND 1)",
            name="ck_observations_fraction_range",
        ),
    )


# --------------------------------------------------------------------------
# Аномалии и прогноз
# --------------------------------------------------------------------------


class Anomaly(Base):
    """Негативный аномальный период — последовательность дат с устойчивым
    отклонением состояния поля от его собственной ожидаемой динамики.

    Положительные отклонения сознательно не превращаются в события: они видны
    на графике, но не создают повода для выезда.
    """

    __tablename__ = "anomalies"

    id: Mapped[uuid.UUID] = _uuid_pk()
    field_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fields.id", ondelete="CASCADE"), index=True
    )

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)

    severity: Mapped[AnomalySeverity] = mapped_column(_enum(AnomalySeverity, "anomaly_severity"))
    max_zscore: Mapped[float] = mapped_column(Float, nullable=False)
    mean_zscore: Mapped[float | None] = mapped_column(Float)

    # Доля восстановленных точек внутри периода: чем она выше, тем осторожнее вывод.
    restored_fraction: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)

    # Совпавшие факторы: динамика NDMI, температура, осадки. Это гипотеза, а не диагноз.
    factors: Mapped[dict | None] = mapped_column(JSONB)
    # Текст от LLM: объяснение и список того, что проверить на месте.
    explanation: Mapped[str | None] = mapped_column(Text)
    checklist: Mapped[dict | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    field: Mapped[Field] = relationship(back_populates="anomalies")

    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="ck_anomalies_period_order"),
        CheckConstraint("duration_days > 0", name="ck_anomalies_duration_positive"),
    )


class ForecastRun(Base):
    """Метаданные одного прогона прогноза. Сами точки лежат в observations."""

    __tablename__ = "forecast_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    field_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fields.id", ondelete="CASCADE"), index=True
    )
    horizon_days: Mapped[int] = mapped_column(Integer, default=14)
    model_version: Mapped[str | None] = mapped_column(String(100))
    direction: Mapped[str | None] = mapped_column(String(50))   # ожидаемое направление динамики
    risk_level: Mapped[str | None] = mapped_column(String(50))
    confidence: Mapped[float | None] = mapped_column(Float)
    # Если данных не хватило, прогноз не формируется — причина попадает сюда.
    insufficient_reason: Mapped[str | None] = mapped_column(String(200))
    factors: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        # Прогон замещается целиком при каждом пересчёте, поэтому строка на
        # поле должна быть одна. Без ограничения два параллельных пересчёта
        # оставили бы две строки, и чтение выбирало бы произвольную.
        UniqueConstraint("field_id", name="uq_forecast_run_field"),
    )


# --------------------------------------------------------------------------
# Служебные таблицы
# --------------------------------------------------------------------------


class Job(Base):
    """Прогресс обработки. Читается фронтендом через SSE.

    Строка на пару (поле, стадия): интерфейс показывает пользователю список стадий
    и прогресс по каждому полю отдельно.
    """

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    field_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fields.id", ondelete="CASCADE"), index=True
    )
    stage: Mapped[PipelineStage] = mapped_column(_enum(PipelineStage, "pipeline_stage"))
    status: Mapped[JobStatus] = mapped_column(
        _enum(JobStatus, "job_status"), default=JobStatus.QUEUED
    )
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    celery_task_id: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("field_id", "stage", name="uq_job_field_stage"),
        CheckConstraint("progress BETWEEN 0 AND 1", name="ck_jobs_progress_range"),
    )


class SceneAsset(Base):
    """Ссылки на визуализацию снимка: XYZ-тайлы из GEE и превью в объектном хранилище.

    Растры целиком не скачиваем — для карты достаточно тайлов, для PDF достаточно превью.
    """

    __tablename__ = "scene_assets"

    id: Mapped[uuid.UUID] = _uuid_pk()
    field_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fields.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[AssetKind] = mapped_column(_enum(AssetKind, "asset_kind"))

    tile_url: Mapped[str | None] = mapped_column(Text)     # XYZ-шаблон из ee.Image.getMapId()
    thumb_key: Mapped[str | None] = mapped_column(String(500))  # ключ объекта в S3
    scene_id: Mapped[str | None] = mapped_column(String(200))
    # Ссылки GEE живут ограниченное время, поэтому храним срок годности.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("field_id", "date", "kind", name="uq_scene_asset_identity"),
    )


class RawCache(Base):
    """Кэш ответов внешних источников.

    Нужен по двум причинам: повторный анализ того же полигона не должен снова
    ходить в GEE, и на защите проекта результат должен воспроизводиться даже
    при недоступном внешнем API.
    """

    __tablename__ = "raw_cache"

    # Ключ — хэш от имени провайдера и параметров запроса.
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), index=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
