"""Климатическая норма поля — ожидаемая динамика NDVI.

Норма строится по собственной истории поля за предыдущие сезоны, а не по
справочнику культур и не по соседним участкам. Причина продуктовая: поле
сравнивается само с собой, поэтому вывод не зависит от точности определения
культуры и остаётся осмысленным в любом регионе.

Фаза сезона задаётся днём года. Дата посева для выравнивания сезонов между
собой сознательно не используется, и это важная оговорка.

Казалось бы, «дней от посева» точнее дня года, поскольку учитывает фактическое
развитие культуры. Но пользователь указывает дату посева только для текущего
сезона, а норма строится по предыдущим. Подставлять ту же дату в прошлые годы
бессмысленно: фаза превратится в день года со сдвигом на константу, а окно
отбирается по модулю разности фаз — результат не изменится ни на йоту.
Выравнивание по посеву заработает лишь тогда, когда появятся даты посева
за каждый сезон.

Отсюда известное ограничение метода: если в анализируемом году сеяли заметно
позже обычного, отставание кривой будет прочитано как угнетение. Сервис обязан
показывать такой вывод как гипотезу, а не как диагноз.

Оценка в точке берётся по окну соседних дней года: наблюдений на конкретный
день за 3-4 сезона слишком мало, чтобы говорить о среднем и разбросе.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import numpy as np

logger = logging.getLogger(__name__)

# Полуширина окна по фазе сезона, дни. Компромисс: узкое окно даёт неустойчивую
# оценку, широкое — размывает быстрые фазы вроде выхода в трубку.
PHASE_WINDOW_DAYS = 15

# Минимум наблюдений в окне, ниже которого норма считается неопределённой.
MIN_SAMPLES_IN_WINDOW = 3

# Нижняя граница стандартного отклонения. Без неё в фазах со стабильным NDVI
# знаменатель z-score стремится к нулю и любое колебание выглядит аномалией.
MIN_STD = 0.03


@dataclass(slots=True)
class ClimatologyPoint:
    mean: float
    std: float
    samples: int


@dataclass(slots=True)
class Climatology:
    """Норма поля вместе с описанием того, на чём она построена."""

    by_phase: dict[int, ClimatologyPoint]
    phase_kind: str          # всегда "day_of_year", см. докстроку модуля
    sowing_known: bool       # известна ли дата посева (на расчёт не влияет)
    seasons_used: int
    samples_total: int
    available: bool
    reason: str | None = None

    def estimate(self, phase: int) -> ClimatologyPoint | None:
        return self.by_phase.get(phase)

    def zscore(self, phase: int, value: float) -> float | None:
        point = self.estimate(phase)
        if point is None:
            return None
        return (value - point.mean) / point.std


def phase_of(day: date, sowing_date: date | None = None) -> int:
    """Фаза сезона для даты — день года.

    Аргумент `sowing_date` сохранён в сигнатуре ради явности вызовов, но на
    расчёт не влияет: причина описана в докстроке модуля.
    """
    return day.timetuple().tm_yday


def build(
    history: list[tuple[date, float]],
    target_dates: list[date],
    sowing_date: date | None,
    exclude_year: int | None = None,
) -> Climatology:
    """Построить норму по историческим наблюдениям.

    `history` — пары (дата, NDVI) за все доступные сезоны. Наблюдения года,
    который анализируется, исключаются: иначе аномалия вошла бы в собственную
    норму и сама себя замаскировала.
    """
    # Норма всегда строится по дню года; дата посева попадает в описание,
    # чтобы пользователь видел, учтена она или нет.
    phase_kind = "day_of_year"
    sowing_known = sowing_date is not None

    samples = [
        (phase_of(day), value)
        for day, value in history
        if value is not None and (exclude_year is None or day.year != exclude_year)
    ]
    seasons = {day.year for day, _ in history if exclude_year is None or day.year != exclude_year}

    if len(samples) < MIN_SAMPLES_IN_WINDOW or len(seasons) < 1:
        return Climatology(
            by_phase={},
            phase_kind=phase_kind,
            sowing_known=sowing_known,
            seasons_used=len(seasons),
            samples_total=len(samples),
            available=False,
            reason="недостаточно собственной истории поля для построения нормы",
        )

    phases = np.array([phase for phase, _ in samples], dtype=float)
    values = np.array([value for _, value in samples], dtype=float)

    by_phase: dict[int, ClimatologyPoint] = {}
    for target in target_dates:
        phase = phase_of(target)
        if phase in by_phase:
            continue

        # День года цикличен: 5 января и 360-й день отстоят на 10 суток.
        distance = np.abs(phases - phase)
        distance = np.minimum(distance, 365.0 - distance)

        selected = values[distance <= PHASE_WINDOW_DAYS]
        if selected.size < MIN_SAMPLES_IN_WINDOW:
            continue

        by_phase[phase] = ClimatologyPoint(
            # Медиана вместо среднего: один аномальный сезон в короткой истории
            # не должен утаскивать норму за собой.
            mean=float(np.median(selected)),
            std=float(max(np.std(selected), MIN_STD)),
            samples=int(selected.size),
        )

    if not by_phase:
        return Climatology(
            by_phase={},
            phase_kind=phase_kind,
            sowing_known=sowing_known,
            seasons_used=len(seasons),
            samples_total=len(samples),
            available=False,
            reason="история поля не покрывает анализируемые фазы сезона",
        )

    return Climatology(
        by_phase=by_phase,
        phase_kind=phase_kind,
        sowing_known=sowing_known,
        seasons_used=len(seasons),
        samples_total=len(samples),
        available=True,
    )
