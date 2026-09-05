"""Слияние веток: сигналы движка аномалий и справочник хозяйств.

Ветки `f1c93a6b27d4` (сигналы движка детекции) и `c7f3e91a4b58` (справочник
хозяйств вместе с его заполнением) отошли от общего предка `e7a2b9d40c31` и
после мёржа остались двумя головами. На базе, куда миграции накатывались по
мере разработки, это незаметно; на чистой `alembic upgrade head` отказывается
выбирать между ними и падает — то есть развернуть сервис с нуля нельзя.

Ревизия только сводит ветки. Схему она не трогает: правки не пересекаются —
одна ветка добавляет колонки к аномалиям, вторая заводит таблицу хозяйств.

Revision ID: b8d5e2f1c74a
Revises: f1c93a6b27d4, c7f3e91a4b58
"""

from collections.abc import Sequence

revision: str = "b8d5e2f1c74a"
down_revision: tuple[str, str] = ("f1c93a6b27d4", "c7f3e91a4b58")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
