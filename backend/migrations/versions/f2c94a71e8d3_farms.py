"""Хозяйство как отдельная сущность, поле принадлежит хозяйству.

Появляется государственный сценарий: решение о поддержке принимается по
хозяйству целиком, поэтому у полей появляется владелец, а у документов —
адресат и место в списке.

Хозяйство заводится внутри проекта. Реестр сравнивает хозяйства между собой,
а сравнимы они только на общем периоде наблюдения — период же лежит
на проекте и общий для всех его полей.

Существующим полям хозяйство не назначается. Приписать их выдуманному
владельцу означало бы записать в реестр то, чего никто не сообщал; в
интерфейсе они видны отдельной группой и переносятся вручную. Это то же
решение, что и с обязательной культурой в предыдущей миграции продукта.

Revision ID: f2c94a71e8d3
Revises: e7a2b9d40c31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f2c94a71e8d3"
down_revision: str | None = "e7a2b9d40c31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "farms",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("inn", sa.String(length=12), nullable=True),
        sa.Column("legal_form", sa.String(length=50), nullable=True),
        sa.Column("district", sa.String(length=200), nullable=True),
        sa.Column("region", sa.String(length=200), nullable=True),
        sa.Column("contact", sa.String(length=200), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_farm_project_name"),
        # Нужна ключу из `fields`: составной внешний ключ ссылается на пару
        # колонок, а она обязана быть уникальной на стороне родителя.
        sa.UniqueConstraint("project_id", "id", name="uq_farm_project_identity"),
    )
    op.create_index("ix_farms_project_id", "farms", ["project_id"])

    op.add_column(
        "fields", sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_index("ix_fields_farm_id", "fields", ["farm_id"])
    # Ключ составной: он запрещает приписать поле хозяйству из другого проекта.
    # `SET NULL (farm_id)` со списком колонок — синтаксис PostgreSQL 15+; без
    # списка удаление хозяйства обнуляло бы и project_id, объявленный NOT NULL.
    op.execute(
        "ALTER TABLE fields ADD CONSTRAINT fk_fields_farm "
        "FOREIGN KEY (project_id, farm_id) REFERENCES farms (project_id, id) "
        "ON DELETE SET NULL (farm_id)"
    )

    op.create_table(
        "generated_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("field_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("filename", sa.String(length=300), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=True),
        sa.Column("pages", sa.Integer(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["farm_id"], ["farms.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["field_id"], ["fields.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key", name="uq_generated_report_storage_key"),
    )
    op.create_index("ix_generated_reports_project_id", "generated_reports", ["project_id"])
    op.create_index("ix_generated_reports_farm_id", "generated_reports", ["farm_id"])
    op.create_index("ix_generated_reports_field_id", "generated_reports", ["field_id"])
    op.create_index(
        "ix_generated_reports_project_created", "generated_reports", ["project_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("generated_reports")
    op.drop_constraint("fk_fields_farm", "fields", type_="foreignkey")
    op.drop_index("ix_fields_farm_id", table_name="fields")
    op.drop_column("fields", "farm_id")
    op.drop_index("ix_farms_project_id", table_name="farms")
    op.drop_table("farms")
