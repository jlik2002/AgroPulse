"""Сигналы движка детекции на карточке аномалии.

Детектор аномалий переведён на движок по текущему ряду (LOWESS-базлайн,
робастные z-score остатка и наклона, поиск структурных переломов), а
климатическая норма поля стала опциональным историческим сигналом. Событие
теперь несёт единый балл `anomaly_score` 0..100 и разложение сигналов в пике:
`level_z`, `slope_z`, `historical_z`, `change_point_nearby`.

Значения не переносятся из прежних строк: пересчитать балл движка из старых
чисел нельзя, а выдумать — значит записать в данные то, чего не считали. Поля
без пересчёта получают нейтральные значения по умолчанию (`anomaly_score = 0`,
`change_point_nearby = false`, остальные NULL) и обновятся при следующем прогоне.

Revision ID: f1c93a6b27d4
Revises: e7a2b9d40c31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1c93a6b27d4"
down_revision: str | None = "e7a2b9d40c31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default нужен только на время добавления колонок к существующим
    # строкам: NOT NULL без него не пройдёт. После заливки значение по умолчанию
    # на уровне БД снимаем — значения проставляет пересчёт, а не вставка.
    op.add_column(
        "anomalies",
        sa.Column("anomaly_score", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "anomalies",
        sa.Column(
            "change_point_nearby",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("anomalies", sa.Column("level_z", sa.Float(), nullable=True))
    op.add_column("anomalies", sa.Column("slope_z", sa.Float(), nullable=True))
    op.add_column("anomalies", sa.Column("historical_z", sa.Float(), nullable=True))

    op.alter_column("anomalies", "anomaly_score", server_default=None)
    op.alter_column("anomalies", "change_point_nearby", server_default=None)


def downgrade() -> None:
    op.drop_column("anomalies", "historical_z")
    op.drop_column("anomalies", "slope_z")
    op.drop_column("anomalies", "level_z")
    op.drop_column("anomalies", "change_point_nearby")
    op.drop_column("anomalies", "anomaly_score")
