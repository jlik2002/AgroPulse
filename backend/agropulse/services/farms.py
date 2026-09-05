"""Сценарии работы с хозяйством.

Здесь только жизненный цикл сущности: завести, переименовать, удалить.
Справочник общий и проекту не принадлежит — хозяйство существует независимо
от того, за какой период смотрели на его поля.

Всё, что считается по результатам анализа — индекс потребности в поддержке,
реестр, достоверность — живёт в `AnalysisService`. Там же появляется проект:
заключение считается по полям хозяйства внутри одного проекта, потому что
период наблюдения общий именно у полей проекта.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from agropulse.db.models import Farm
from agropulse.db.uow import UnitOfWork
from agropulse.errors import DuplicateFarmNameError, FarmNotFoundError

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CreateFarmCommand:
    name: str
    inn: str | None = None
    legal_form: str | None = None
    district: str | None = None
    region: str | None = None
    contact: str | None = None
    note: str | None = None


@dataclass(slots=True)
class UpdateFarmCommand:
    """Частичное обновление: `None` означает «не менять»."""

    name: str | None = None
    inn: str | None = None
    legal_form: str | None = None
    district: str | None = None
    region: str | None = None
    contact: str | None = None
    note: str | None = None


# Реквизиты, которые правятся однообразно. Название вынесено отдельно:
# у него есть проверка на уникальность внутри проекта.
_DETAILS = ("inn", "legal_form", "district", "region", "contact", "note")


class FarmService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def create(self, command: CreateFarmCommand) -> Farm:
        if self._uow.farms.find_by_name(command.name) is not None:
            raise DuplicateFarmNameError(name=command.name)

        farm = self._uow.farms.add(
            Farm(
                name=command.name,
                inn=command.inn,
                legal_form=command.legal_form,
                district=command.district,
                region=command.region,
                contact=command.contact,
                note=command.note,
            )
        )
        self._uow.commit()
        logger.info("farm_created", extra={"farm_id": str(farm.id)})
        return farm

    def list_all(self) -> list[Farm]:
        """Весь справочник. Отбора по проекту нет намеренно.

        Хозяйство, заведённое в одном проекте, должно быть доступно в другом:
        иначе одно и то же предприятие приходится создавать заново под каждый
        период наблюдения, и в реестре оно двоится.
        """
        return self._uow.farms.list_all()

    def get(self, farm_id: uuid.UUID) -> Farm:
        farm = self._uow.farms.get(farm_id)
        if farm is None:
            raise FarmNotFoundError(farm_id=str(farm_id))
        return farm

    def update(self, farm_id: uuid.UUID, command: UpdateFarmCommand) -> Farm:
        farm = self.get(farm_id)

        if command.name is not None and command.name != farm.name:
            if self._uow.farms.find_by_name(command.name) is not None:
                raise DuplicateFarmNameError(name=command.name)
            farm.name = command.name

        for attribute in _DETAILS:
            value = getattr(command, attribute)
            if value is not None:
                # Пустая строка — это «стереть»: реквизит могли ввести ошибочно,
                # и способ убрать его нужен. У культуры такого нет, потому что
                # она обязательна, а ИНН — нет.
                setattr(farm, attribute, value or None)

        self._uow.commit()
        logger.info("farm_updated", extra={"farm_id": str(farm_id)})
        return farm

    def delete(self, farm_id: uuid.UUID) -> int:
        """Удалить хозяйство. Поля остаются и теряют владельца.

        Возвращает число осиротевших полей — интерфейс предупреждает о нём
        до удаления. Справочник общий, поэтому осиротеть могут поля сразу
        нескольких проектов, и число относится ко всем. Каскад здесь был бы
        разрушительным: вместе с полями ушли бы собранные наблюдения, а это
        часы обращений к Earth Engine и единственная копия ряда.

        Ссылка снимается явно, хотя её сняла бы и база: внешний ключ объявлен
        с `ON DELETE SET NULL`. Дублирование намеренное — сессия живёт
        с `expire_on_commit=False`, и уже прочитанные поля иначе остались бы
        в памяти с указателем на удалённое хозяйство.
        """
        farm = self.get(farm_id)
        orphaned = self._uow.fields.list_for_farm(farm_id)
        for field in orphaned:
            field.farm_id = None

        self._uow.farms.delete(farm)
        self._uow.commit()
        logger.info(
            "farm_deleted", extra={"farm_id": str(farm_id), "orphaned_fields": len(orphaned)}
        )
        return len(orphaned)
