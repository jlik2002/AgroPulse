"""Один вердикт о доверии вместо трёх показателей.

`confidence` складывался из длительности, числа точек суточной сетки (то есть
снова длительности) и доли восстановленных значений. Последняя равна примерно
0,8 у любого события по построению: восстановление заполняет каждый день
периода, а Sentinel-2 летает раз в пять суток. Замер по базе на момент
миграции: 0,75-1,00 без единого исключения.

`corroboration` списывал один физический факт — облачное окно — трижды:
понижением веса оптики, потерей балла за устойчивость и отдельным штрафом.
Событие, на котором сошлись радар и погода, получало «слабое подтверждение».

Оба заменяются полем `trust` с тремя состояниями. Значения не переносятся:
пересчитать их из прежних чисел нельзя, а выдумать — значит повторить
исходную ошибку. Поля без пересчёта показываются как «не проверено».

Revision ID: e7a2b9d40c31
Revises: d5c81f37a6b2
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7a2b9d40c31"
down_revision: str | None = "d5c81f37a6b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("anomalies", sa.Column("trust", sa.String(length=20), nullable=True))
    op.drop_column("anomalies", "corroboration")
    op.drop_column("anomalies", "confidence")


def downgrade() -> None:
    op.add_column("anomalies", sa.Column("confidence", sa.Float(), nullable=True))
    op.add_column("anomalies", sa.Column("corroboration", sa.Integer(), nullable=True))
    op.drop_column("anomalies", "trust")
