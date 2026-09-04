"""Поиск негативных аномальных периодов.

Аномалия здесь — не отдельная просевшая точка, а устойчивое отклонение вниз от
собственной нормы поля. Одиночный выброс чаще означает недомаскированное облако
или ошибку данных, чем угнетение растительности, поэтому событием он не становится.

Положительные отклонения сознательно не порождают событий: они видны на графике,
но не являются поводом отправлять агронома в поле.

Пороги z-score взяты из постановки задачи: от -1 до -2 — угнетение биомассы,
ниже -2 — критическая аномалия.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field as dataclass_field
from datetime import date

from agropulse.analytics.climatology import Climatology, phase_of
from agropulse.db.models import AnomalySeverity, ValueType

logger = logging.getLogger(__name__)

Z_MODERATE = -1.0
Z_CRITICAL = -2.0

# Соседние отклонения сливаются в один период, если разрыв между ними не больше
# этого числа суток. Иначе облачная неделя посреди засухи разрезала бы одно
# событие на два.
MERGE_GAP_DAYS = 12

# Событие должно опираться минимум на две точки: одна точка — это выброс.
MIN_POINTS = 2
MIN_DURATION_DAYS = 5


@dataclass(slots=True)
class SeriesSample:
    """Точка ряда, поданная на анализ."""

    date: date
    ndvi: float
    value_type: ValueType
    ndmi: float | None = None
    temperature: float | None = None
    precipitation: float | None = None


@dataclass(slots=True)
class AnomalyPeriod:
    start_date: date
    end_date: date
    duration_days: int
    severity: AnomalySeverity
    max_zscore: float
    mean_zscore: float
    points: int
    restored_fraction: float
    confidence: float
    factors: dict = dataclass_field(default_factory=dict)


def detect(
    samples: list[SeriesSample], climatology: Climatology, sowing_date: date | None = None
) -> tuple[list[AnomalyPeriod], dict[date, float]]:
    """Найти аномальные периоды и вернуть z-score по датам.

    `sowing_date` принимается для единообразия вызова, но на расчёт фазы
    не влияет — см. докстроку `analytics.climatology`.
    """
    if not climatology.available:
        return [], {}

    zscores: dict[date, float] = {}
    flagged: list[tuple[SeriesSample, float]] = []

    for sample in sorted(samples, key=lambda s: s.date):
        z = climatology.zscore(phase_of(sample.date), sample.ndvi)
        if z is None:
            continue
        zscores[sample.date] = round(z, 4)
        if z < Z_MODERATE:
            flagged.append((sample, z))

    groups = _group(flagged)

    periods: list[AnomalyPeriod] = []
    for group in groups:
        period = _build_period(group)
        if period is not None:
            periods.append(period)

    # Самые тяжёлые события — первыми: интерфейс показывает их пользователю в этом порядке.
    periods.sort(key=lambda p: (p.max_zscore, -p.duration_days))
    return periods, zscores


def _group(flagged: list[tuple[SeriesSample, float]]) -> list[list[tuple[SeriesSample, float]]]:
    """Слить соседние отклонения в группы."""
    groups: list[list[tuple[SeriesSample, float]]] = []
    for item in flagged:
        if groups and (item[0].date - groups[-1][-1][0].date).days <= MERGE_GAP_DAYS:
            groups[-1].append(item)
        else:
            groups.append([item])
    return groups


def _build_period(group: list[tuple[SeriesSample, float]]) -> AnomalyPeriod | None:
    samples = [sample for sample, _ in group]
    zs = [z for _, z in group]

    start, end = samples[0].date, samples[-1].date
    duration = (end - start).days + 1

    if len(group) < MIN_POINTS and duration < MIN_DURATION_DAYS:
        return None

    restored = sum(1 for s in samples if s.value_type == ValueType.RESTORED)
    restored_fraction = restored / len(samples)

    max_z = min(zs)
    severity = AnomalySeverity.CRITICAL if max_z < Z_CRITICAL else AnomalySeverity.MODERATE

    return AnomalyPeriod(
        start_date=start,
        end_date=end,
        duration_days=duration,
        severity=severity,
        max_zscore=round(max_z, 4),
        mean_zscore=round(sum(zs) / len(zs), 4),
        points=len(group),
        restored_fraction=round(restored_fraction, 3),
        confidence=_confidence(len(group), restored_fraction, duration),
        factors=_factors(samples),
    )


def _confidence(points: int, restored_fraction: float, duration: int) -> float:
    """Уверенность в событии.

    Растёт с числом подтверждающих точек и длительностью, падает с долей
    восстановленных значений: вывод, опирающийся на интерполяцию, слабее вывода
    по фактическим наблюдениям.
    """
    from_points = min(points / 5.0, 1.0)
    from_duration = min(duration / 20.0, 1.0)
    penalty = 1.0 - 0.5 * restored_fraction
    return round(max(0.05, (0.5 * from_points + 0.5 * from_duration) * penalty), 3)


def _factors(samples: list[SeriesSample]) -> dict:
    """Совпавшие с аномалией факторы.

    Это гипотеза, а не диагноз: сервис показывает, что происходило одновременно
    с падением индекса, и оставляет вывод о причине человеку.
    """
    ndmi = [s.ndmi for s in samples if s.ndmi is not None]
    temperature = [s.temperature for s in samples if s.temperature is not None]
    precipitation = [s.precipitation for s in samples if s.precipitation is not None]

    factors: dict = {}
    if ndmi:
        factors["ndmi_mean"] = round(sum(ndmi) / len(ndmi), 4)
        factors["ndmi_trend"] = round(ndmi[-1] - ndmi[0], 4) if len(ndmi) > 1 else 0.0
    if temperature:
        factors["temperature_mean"] = round(sum(temperature) / len(temperature), 2)
        factors["temperature_max"] = round(max(temperature), 2)
    if precipitation:
        factors["precipitation_sum"] = round(sum(precipitation), 2)
        factors["dry_days"] = sum(1 for value in precipitation if value < 1.0)

    hypotheses: list[str] = []
    if factors.get("ndmi_trend", 0.0) < -0.05 and factors.get("precipitation_sum", 99.0) < 10.0:
        hypotheses.append("снижение индекса влажности при малом количестве осадков — водный стресс")
    if factors.get("temperature_max", 0.0) > 32.0:
        hypotheses.append("высокие температуры в период отклонения — тепловой стресс")
    if factors.get("precipitation_sum", 0.0) > 60.0:
        hypotheses.append("обильные осадки — возможно переувлажнение или полегание")
    if not hypotheses:
        hypotheses.append("явных погодных причин не выявлено — требуется осмотр на месте")
    factors["hypotheses"] = hypotheses
    return factors
