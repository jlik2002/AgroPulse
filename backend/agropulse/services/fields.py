"""Сценарии работы с полем: контур, временной ряд, запуск обработки."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from agropulse.db.models import Field, FieldSource, FieldStatus, Observation, ValueType
from agropulse.db.uow import UnitOfWork
from agropulse.errors import (
    EmptyProjectError,
    FarmNotFoundError,
    FieldNotFoundError,
    ProjectNotFoundError,
)
from agropulse.geometry import to_wkt_element, validate_polygon
from agropulse.tasks.publisher import TaskPublisher

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CreateFieldCommand:
    name: str
    geometry: dict
    # Хозяйство и культура текущего сезона обязательны — см. `schemas/field.py`.
    farm_id: uuid.UUID
    crop: str
    sowing_date: date | None = None
    source: FieldSource = FieldSource.DRAWN
    external_ref: str | None = None


@dataclass(slots=True)
class UpdateFieldCommand:
    name: str | None = None
    geometry: dict | None = None
    farm_id: uuid.UUID | None = None
    crop: str | None = None
    sowing_date: date | None = None


@dataclass(slots=True)
class FieldTimeseries:
    """Ряд поля вместе со сводкой качества данных."""

    field: Field
    period_from: date
    period_to: date
    observations: list[Observation]
    stats: dict[str, float | int | None]


@dataclass(slots=True)
class ProcessingAccepted:
    field_id: uuid.UUID
    task_id: str


class FieldService:
    def __init__(self, uow: UnitOfWork, publisher: TaskPublisher) -> None:
        self._uow = uow
        self._publisher = publisher

    # ------------------------------------------------------------------
    # Чтение
    # ------------------------------------------------------------------

    def get(self, field_id: uuid.UUID) -> Field:
        field = self._uow.fields.get_with_project(field_id)
        if field is None:
            raise FieldNotFoundError(field_id=str(field_id))
        return field

    def list_for_project(self, project_id: uuid.UUID) -> list[Field]:
        self._require_project(project_id)
        return self._uow.fields.list_for_project(project_id)

    def timeseries(self, field_id: uuid.UUID) -> FieldTimeseries:
        field = self.get(field_id)
        observations = self._uow.observations.list_for_field(field_id)
        return FieldTimeseries(
            field=field,
            period_from=field.project.period_from,
            period_to=field.project.period_to,
            observations=observations,
            stats=_timeseries_stats(observations),
        )

    # ------------------------------------------------------------------
    # Изменение
    # ------------------------------------------------------------------

    def create(self, project_id: uuid.UUID, command: CreateFieldCommand) -> Field:
        """Добавить поле в проект.

        Полигон приходит либо нарисованным вручную, либо выбранным из открытого
        источника контуров — различие сохраняется в поле `source`.
        """
        self._require_project(project_id)
        self._require_farm(project_id, command.farm_id)
        geometry, area_ha = validate_polygon(command.geometry)

        field = self._uow.fields.add(
            Field(
                project_id=project_id,
                farm_id=command.farm_id,
                name=command.name,
                geom=to_wkt_element(geometry),
                area_ha=area_ha,
                crop=command.crop,
                sowing_date=command.sowing_date,
                source=command.source,
                external_ref=command.external_ref,
                status=FieldStatus.PENDING,
            )
        )
        self._uow.commit()
        logger.info(
            "field_created",
            extra={"field_id": str(field.id), "project_id": str(project_id)},
        )
        return field

    def update(self, field_id: uuid.UUID, command: UpdateFieldCommand) -> Field:
        """Изменить поле и, если правка обесценила расчёт, пересчитать его.

        Смена контура делает недействительными все производные данные: прежние
        наблюдения относятся к другой области, а построенные по ним аномалии,
        прогноз и оценка риска — к другому полю. Поэтому производные данные
        снимаются целиком и в одной транзакции с изменением геометрии, а следом
        поле уходит на полный цикл — иначе оно осталось бы пустым до тех пор,
        пока пользователь не догадается запустить анализ вручную.

        Культура и дата посева ряд не меняют, но меняют его трактовку: они
        уходят в сервис моделей и в текст отчёта. Собранные наблюдения при этом
        остаются годными, поэтому достаточно пересчёта без обращения к Earth
        Engine. Раньше не делалось ни того, ни другого: пользователь указывал
        культуру, а отчёт оставался прежним.

        Переименование поля и перенос его в другое хозяйство на расчёт
        не влияют и ничего не запускают: хозяйство не входит ни в один
        показатель поля, оно определяет только, в чью строку реестра
        сложится результат.
        """
        field = self.get(field_id)

        if command.farm_id is not None and command.farm_id != field.farm_id:
            self._require_farm(field.project_id, command.farm_id)

        geometry_changed = command.geometry is not None
        # Сравниваем со значением в базе: повторная отправка той же культуры
        # приходит при каждом сохранении формы и пересчёт запускать не должна.
        interpretation_changed = any(
            getattr(command, attribute) is not None
            and getattr(command, attribute) != getattr(field, attribute)
            for attribute in ("crop", "sowing_date")
        )

        if geometry_changed:
            geometry, area_ha = validate_polygon(command.geometry)
            field.geom = to_wkt_element(geometry)
            field.area_ha = area_ha
            self._reset_derived_data(field)

        for attribute in ("name", "farm_id", "crop", "sowing_date"):
            value = getattr(command, attribute)
            if value is not None:
                setattr(field, attribute, value)

        # Поле, которое ещё ни разу не считалось, пересчитывать нечего:
        # оно уйдёт в обработку вместе со всем проектом.
        analyzed = field.status not in (FieldStatus.PENDING, FieldStatus.FAILED)
        if not geometry_changed and interpretation_changed and analyzed:
            field.status = FieldStatus.PENDING

        self._uow.commit()

        # Задачи публикуются после фиксации транзакции: воркер может забрать
        # их мгновенно и обязан увидеть в базе уже изменённое поле.
        if geometry_changed:
            task_id = self._publisher.publish_field_processing(field.id)
            logger.info(
                "field_reprocessing_requested",
                extra={"field_id": str(field_id), "celery_task_id": task_id, "cause": "geometry"},
            )
        elif interpretation_changed and analyzed:
            task_id = self._publisher.publish_field_analysis(field.id)
            logger.info(
                "field_reanalysis_requested",
                extra={
                    "field_id": str(field_id),
                    "celery_task_id": task_id,
                    "cause": "interpretation",
                },
            )

        logger.info("field_updated", extra={"field_id": str(field_id)})
        return field

    def delete(self, field_id: uuid.UUID) -> None:
        field = self.get(field_id)
        self._uow.fields.delete(field)
        self._uow.commit()
        logger.info("field_deleted", extra={"field_id": str(field_id)})

    # ------------------------------------------------------------------
    # Запуск обработки
    # ------------------------------------------------------------------

    def request_processing(self, field_id: uuid.UUID) -> ProcessingAccepted:
        """Поставить полную обработку поля в очередь.

        Задача публикуется после фиксации транзакции, а не внутри неё: воркер
        может забрать её мгновенно, и он обязан увидеть в базе актуальное поле.
        """
        field = self.get(field_id)
        task_id = self._publisher.publish_field_processing(field.id)
        logger.info(
            "field_processing_requested",
            extra={"field_id": str(field.id), "celery_task_id": task_id},
        )
        return ProcessingAccepted(field_id=field.id, task_id=task_id)

    def request_project_processing(
        self, project_id: uuid.UUID, field_ids: Sequence[uuid.UUID] | None = None
    ) -> list[ProcessingAccepted]:
        """Поставить обработку полей проекта.

        `field_ids` ограничивает запуск выбранными полями. Это не украшение:
        сбор по одному полю занимает минуты и расходует квоту Earth Engine,
        поэтому добавив одно поле к десяти уже посчитанным, пользователь
        должен иметь возможность посчитать только его. Без списка обрабатывается
        весь проект — так работает первый запуск.

        Поля обрабатываются независимыми задачами: отказ по одному полю
        не должен останавливать остальные.
        """
        self._require_project(project_id)
        fields = self._uow.fields.list_for_project(project_id)
        if not fields:
            raise EmptyProjectError(project_id=str(project_id))

        if field_ids is not None:
            # Отбираем из полей проекта, а не доверяем списку: идентификатор
            # чужого поля не должен запускать обработку через этот проект.
            requested = set(field_ids)
            known = {field.id for field in fields}
            unknown = requested - known
            if unknown:
                raise FieldNotFoundError(field_id=str(next(iter(unknown))))
            fields = [field for field in fields if field.id in requested]
            if not fields:
                raise EmptyProjectError(project_id=str(project_id))

        accepted = [
            ProcessingAccepted(
                field_id=field.id,
                task_id=self._publisher.publish_field_processing(field.id),
            )
            for field in fields
        ]
        logger.info(
            "project_processing_requested",
            extra={
                "project_id": str(project_id),
                "fields": len(accepted),
                "selective": field_ids is not None,
            },
        )
        return accepted

    # ------------------------------------------------------------------

    def _require_project(self, project_id: uuid.UUID) -> None:
        if not self._uow.projects.exists(project_id):
            raise ProjectNotFoundError(project_id=str(project_id))

    def _require_farm(self, project_id: uuid.UUID, farm_id: uuid.UUID) -> None:
        """Хозяйство должно существовать и принадлежать тому же проекту.

        Тот же инвариант закреплён составным внешним ключом в схеме, но его
        нарушение доехало бы до клиента пятисоткой от базы. Здесь оно
        превращается в 404 с внятным кодом.
        """
        farm = self._uow.farms.get(farm_id)
        if farm is None or farm.project_id != project_id:
            raise FarmNotFoundError(farm_id=str(farm_id), project_id=str(project_id))

    def _reset_derived_data(self, field: Field) -> None:
        self._uow.observations.delete_for_field(field.id)
        self._uow.anomalies.replace_for_field(field.id, [])
        self._uow.forecasts.delete_for_field(field.id)
        field.status = FieldStatus.PENDING
        field.risk_score = None
        field.risk_breakdown = None
        field.data_quality = None


def _timeseries_stats(observations: list[Observation]) -> dict[str, float | int | None]:
    """Сводка качества данных: пользователь должен видеть, на чём основан вывод."""
    observed = [o for o in observations if o.value_type == ValueType.OBSERVED]
    with_ndvi = [o for o in observed if o.ndvi_mean is not None]
    valid_fractions = [o.valid_fraction for o in with_ndvi if o.valid_fraction is not None]

    return {
        "total_points": len(observations),
        "observed": len(observed),
        "restored": sum(1 for o in observations if o.value_type == ValueType.RESTORED),
        "forecast": sum(1 for o in observations if o.value_type == ValueType.FORECAST),
        "scenes_with_ndvi": len(with_ndvi),
        "mean_valid_fraction": (
            round(sum(valid_fractions) / len(valid_fractions), 4) if valid_fractions else None
        ),
    }
