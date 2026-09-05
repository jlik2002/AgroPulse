"""Поиск негативных аномальных периодов.

Аномалия здесь — не отдельная просевшая точка, а устойчивое отклонение вниз от
собственной нормы поля. Одиночный выброс чаще означает недомаскированное облако
или ошибку данных, чем угнетение растительности, поэтому событием он не становится.

Положительные отклонения сознательно не порождают событий: они видны на графике,
но не являются поводом отправлять агронома в поле.

Пороги z-score взяты из постановки задачи: от -1 до -2 — угнетение биомассы,
ниже -2 — критическая аномалия.

Модуль отвечает только на вопрос «есть ли устойчивое отклонение». Вопрос
«можно ли этому верить» решается отдельно, в `analytics/trust.py`, по
свидетельствам из независимых источников. Раньше он решался здесь же
числом `confidence`, и число это складывалось из длительности, числа точек
суточной сетки (то есть снова длительности) и доли восстановленных значений,
которая у любого события равна примерно 0,8 по построению. Мера, не зависящая
ни от чего, кроме длительности, называлась уверенностью — этого больше нет.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date

import numpy as np

from agropulse.analytics.climatology import Climatology, phase_of
from agropulse.db.models import AnomalySeverity, ValueType

logger = logging.getLogger(__name__)

Z_MODERATE = -1.0
Z_CRITICAL = -2.0

# Соседние отклонения сливаются в один период, если разрыв между ними не больше
# этого числа суток. Иначе облачная неделя посреди засухи разрезала бы одно
# событие на два.
MERGE_GAP_DAYS = 12

# Порог корреляции между фактической кривой сезона и климатической нормой поля.
# Ниже него считаем, что сезон не совпал с историей по форме — вероятна смена
# культуры в севообороте. Значение выбрано по замеру на четырёх полях двух
# регионов: 0.93 и 0.97 у полей, повторяющих свою норму, против 0.55 и 0.69
# у полей со сменой культуры. Выборка мала, порог подлежит уточнению.
PHASE_MISMATCH_CORRELATION = 0.75
MIN_POINTS_FOR_CORRELATION = 6

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
    # Вердикт о доверии. Выносится не здесь: этот модуль отвечает только за то,
    # есть ли отклонение, а можно ли ему верить — вопрос независимых источников
    # и решается в `analytics/trust.py`.
    trust: str | None = None
    # Признак того, что сезон в целом не совпал по фазе с историей поля.
    phase_mismatch: bool = False
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

    # Сезон мог целиком не совпасть с нормой по фазе. Тогда найденные
    # отклонения — артефакт сравнения с другой культурой, а не угнетение.
    mismatch, correlation = detect_phase_mismatch(samples, climatology)

    groups = _group(flagged)

    periods: list[AnomalyPeriod] = []
    for group in groups:
        period = _build_period(group)
        if period is not None:
            # Корреляцию показываем всегда: она объясняет, почему вывод
            # снижен или, наоборот, почему ему можно доверять.
            period.factors["curve_correlation"] = correlation
            if mismatch:
                period.phase_mismatch = True
                # factors уезжает в API как есть, поэтому признак кладём и туда.
                period.factors["phase_mismatch"] = True
                # Прежде здесь вдвое резалась уверенность — число падало,
                # а причина оставалась невидимой. Теперь признак уходит
                # в вердикт о доверии (`analytics/trust.py`), где он назван
                # словами и виден пользователю.
                period.factors.setdefault("hypotheses", []).insert(
                    0,
                    "динамика поля не совпадает с его историей: вероятна смена культуры "
                    "в севообороте или другие сроки сева, а не угнетение растительности",
                )
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
        factors=_factors(samples),
    )


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


def detect_phase_mismatch(
    samples: list[SeriesSample], climatology: Climatology
) -> tuple[bool, float | None]:
    """Проверить, совпадает ли форма сезона с нормой поля.

    Различие между угнетением и сменой культуры — не в глубине отклонения,
    а в форме кривой. Угнетённое поле повторяет сезонный ход своей нормы,
    просто идёт ниже. Поле, засеянное другой культурой, имеет пик в другое
    время, и кривая расходится с нормой по форме.

    Первая версия проверки сравнивала размах z-score в обе стороны и оказалась
    негодной: при короткой истории норма узкая, и порог сверху превышали все
    поля, включая эталонные. Проверка вырождалась в «есть глубокая аномалия»
    и резала риск любому настоящему событию.

    Мера — коэффициент корреляции Пирсона между фактическими значениями сезона
    и ожидаемыми по норме. Возвращается вместе с вердиктом, чтобы пользователь
    видел основание вывода.
    """
    pairs = [
        (sample.ndvi, point.mean)
        for sample in samples
        if (point := climatology.estimate(phase_of(sample.date))) is not None
    ]
    if len(pairs) < MIN_POINTS_FOR_CORRELATION:
        return False, None

    actual = np.array([value for value, _ in pairs], dtype=float)
    expected = np.array([value for _, value in pairs], dtype=float)
    # Постоянный ряд корреляции не имеет: делить будет не на что.
    if actual.std() == 0 or expected.std() == 0:
        return False, None

    correlation = float(np.corrcoef(actual, expected)[0, 1])
    return correlation < PHASE_MISMATCH_CORRELATION, round(correlation, 3)
