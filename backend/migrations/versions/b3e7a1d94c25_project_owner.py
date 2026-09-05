"""Владелец проекта: анонимный идентификатор посетителя из cookie.

Нужен, чтобы пользователь возвращался к своим проектам после закрытия
браузера. Указатель на проект жил в localStorage и терялся при чистке,
в приватном окне и на другом устройстве; сервер о принадлежности проектов
не знал ничего.

Существующие проекты получают каждый свой случайный идентификатор. Приписать
их одному владельцу было бы хуже: первый же зашедший увидел бы в списке чужие
рабочие пространства. Со своим уникальным они остаются доступны по прямой
ссылке, но в чужом списке не появляются.

Revision ID: b3e7a1d94c25
Revises: a1f4c7e28b90
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b3e7a1d94c25"
down_revision: str | None = "a1f4c7e28b90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Три шага, а не один: колонка не может появиться сразу NOT NULL,
    # пока в таблице есть строки.
    op.add_column(
        "projects",
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    # gen_random_uuid() встроена в PostgreSQL начиная с 13-й версии,
    # расширение pgcrypto подключать не требуется.
    op.execute("UPDATE projects SET owner_id = gen_random_uuid() WHERE owner_id IS NULL")
    op.alter_column("projects", "owner_id", nullable=False)
    op.create_index("ix_projects_owner_id", "projects", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_projects_owner_id", table_name="projects")
    op.drop_column("projects", "owner_id")
