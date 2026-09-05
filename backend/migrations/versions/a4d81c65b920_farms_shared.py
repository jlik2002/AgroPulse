"""Справочник хозяйств становится общим, а не частью проекта.

Хозяйство — объект реального мира: его название, ИНН и район не зависят от
того, за какой период мы смотрели на его поля. Привязка к проекту делала одно
и то же хозяйство невидимым из соседнего проекта и заставляла заводить его
заново под каждый период наблюдения.

Сравнимость оценок при этом не теряется: от периода зависит не хозяйство,
а заключение по нему, — а реестр по-прежнему строится по проекту и ранжирует
только те хозяйства, у которых есть поля в этом проекте. У всех полей проекта
период общий, поэтому баллы сопоставимы.

Отсюда же уходит составной внешний ключ из `fields`: он запрещал приписать
поле хозяйству другого проекта, а проекта у хозяйства больше нет. На его место
встаёт обычный ключ с тем же поведением при удалении — ссылка снимается,
поля и собранные наблюдения остаются.

Revision ID: a4d81c65b920
Revises: f2c94a71e8d3
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a4d81c65b920"
down_revision: str | None = "f2c94a71e8d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("fk_fields_farm", "fields", type_="foreignkey")
    op.create_foreign_key(
        "fk_fields_farm", "fields", "farms", ["farm_id"], ["id"], ondelete="SET NULL"
    )

    op.drop_constraint("uq_farm_project_identity", "farms", type_="unique")
    op.drop_constraint("uq_farm_project_name", "farms", type_="unique")
    # Имя становится единственным адресом хозяйства в справочнике: два
    # одноимённых в реестре неразличимы. Дубликаты возможны только из данных,
    # заведённых до этой миграции в разных проектах, — их снимаем, оставляя
    # то, что завели первым, и переименовывая остальные.
    op.execute(
        """
        UPDATE farms AS f
           SET name = f.name || ' (' || left(f.id::text, 4) || ')'
          FROM (
              SELECT id, row_number() OVER (PARTITION BY name ORDER BY created_at) AS position
                FROM farms
          ) AS ranked
         WHERE ranked.id = f.id AND ranked.position > 1
        """
    )
    op.create_unique_constraint("uq_farm_name", "farms", ["name"])

    op.drop_index("ix_farms_project_id", table_name="farms")
    op.drop_column("farms", "project_id")


def downgrade() -> None:
    # Проект хозяйству возвращается по его полям. У хозяйства без полей его
    # взять неоткуда, поэтому такие строки удаляются: колонка NOT NULL,
    # и выдумать значение здесь означало бы приписать хозяйство наугад.
    op.add_column(
        "farms", sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.execute(
        "UPDATE farms SET project_id = ("
        "  SELECT f.project_id FROM fields f WHERE f.farm_id = farms.id LIMIT 1)"
    )
    op.execute("DELETE FROM farms WHERE project_id IS NULL")
    op.alter_column("farms", "project_id", nullable=False)
    op.create_foreign_key(
        "farms_project_id_fkey", "farms", "projects", ["project_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_farms_project_id", "farms", ["project_id"])

    op.drop_constraint("uq_farm_name", "farms", type_="unique")
    op.create_unique_constraint("uq_farm_project_name", "farms", ["project_id", "name"])
    op.create_unique_constraint("uq_farm_project_identity", "farms", ["project_id", "id"])

    op.drop_constraint("fk_fields_farm", "fields", type_="foreignkey")
    op.execute(
        "ALTER TABLE fields ADD CONSTRAINT fk_fields_farm "
        "FOREIGN KEY (project_id, farm_id) REFERENCES farms (project_id, id) "
        "ON DELETE SET NULL (farm_id)"
    )
