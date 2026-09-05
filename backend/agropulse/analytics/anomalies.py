"""Поиск негативных аномальных периодов в ряду NDVI.

Аномалия здесь — не отдельная просевшая точка, а устойчивое отклонение поля
от его ожидаемой динамики. Одиночный выброс чаще означает недомаскированное
облако или ошибку данных, чем угнетение растительности, поэтому событием он
не становится. Положительные отклонения сознательно не порождают событий: они
видны на графике, но не являются поводом отправлять агронома в поле.

## Движок

Основной детектор работает по самому ряду текущего сезона и не требует истории:

1. Ряд приводится к суточной сетке, малые gaps (до ~14 дней) заполняются PCHIP.
2. LOWESS строит плавную ожидаемую кривую сезона.
3. Остаток `факт − ожидание` превращается в robust z-score через MAD (`level_z`).
4. Отдельно считается наклон и аномальность наклона (`slope_z`).
5. PELT ищет структурные переломы ряда (`change_point_nearby`).
6. Устойчивость отклонения (persistence) и все сигналы сводятся в единый
   `anomaly_score` от 0 до 100.

Одна низкая точка ещё ничего не значит: сильная аномалия — это обычно
комбинация «ниже ожидания + тренд ухудшается + отклонение держится + рядом
структурный перелом».

## Роль климатологии

`analytics/climatology.py` не удалён и остаётся вторым, историческим взглядом на
то же событие. Если у поля есть собственная история за прошлые сезоны, норма по
дню года даёт `historical_z` — насколько поле хуже самого себя в эту фазу. Тогда
именно этот сигнал (порог из постановки: z<−1 угнетение, z<−2 критично) решает,
что считать событием, а движок LOWESS/наклона/переломов обогащает его `anomaly_score`
и объясняет форму. Так поведение на полях с историей остаётся прежним и проверяемым.

Если истории нет, климатология молчит, и детектор опирается только на движок по
текущему ряду. Это и есть причина, по которой старый алгоритм не мог быть главным:
он при отсутствии нормы возвращал пустой результат, а история есть не всегда.

## Что детектор без истории не умеет

Он находит устойчивые просадки уровня — падение, после которого поле держится
ниже собственного предыдущего хода. Он принципиально не может заметить, что весь
сезон целиком прошёл ниже обычного: чтобы сказать «ниже обычного», нужно знать,
каким обычный был, то есть нужна история. Поле, у которого NDVI весь сезон
держится на 0.5 вместо привычных 0.75, без прошлых сезонов выглядит просто полем
с плато на 0.5.

Граница проходит не там, где хотелось бы, а там, где данные позволяют. Замер на
синтетическом сезоне: просадка на 0.25 сразу после фазы роста не опознаётся,
потому что предыдущие две недели сами лежат на подъёме и «уровень до» занижен;
обвал вегетации опознаётся уверенно. Пороги подобраны по смыслу величин, а не
откалиброваны на реальных полях, и подлежат уточнению — как и пороги z в
климатологии.

## Границы ответственности

Модуль отвечает только на вопрос «есть ли устойчивое отклонение». Вопрос «можно
ли этому верить» решается отдельно, в `analytics/trust.py`, по свидетельствам из
независимых источников — и `anomaly_score` с доверием не смешивается: величина
отклонения и надёжность вывода это разные вещи. Причину аномалии (засуха, жара,
переувлажнение) модуль тоже не ставит — это гипотезы в `factors`, а не диагноз.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date

import numpy as np
import pandas as pd
from scipy.interpolate import PchipInterpolator

from agropulse.analytics.climatology import Climatology, phase_of
from agropulse.db.models import AnomalySeverity, ValueType

logger = logging.getLogger(__name__)

# LOWESS — единственная функция, которую мы берём из statsmodels. Если пакета нет,
# опускаемся на скользящую медиану: движок обязан подниматься даже в урезанном
# окружении, просто ожидаемая кривая будет грубее.
try:
    from statsmodels.nonparametric.smoothers_lowess import lowess as _sm_lowess
except Exception:  # pragma: no cover - зависит от окружения
    _sm_lowess = None

# ruptures нужен только для поиска структурных переломов. Его отсутствие не ломает
# детектор: change-point-компонента просто не срабатывает.
try:
    import ruptures as rpt
except Exception:  # pragma: no cover - зависит от окружения
    rpt = None

EPS = 1e-8

# --- пороги отклонения от собственной нормы (climatology) ------------------
# Взяты из постановки задачи: от −1 до −2 — угнетение биомассы, ниже −2 —
# критическая аномалия. По ним же строится флаг события на полях с историей,
# поэтому поведение таких полей совпадает со старым детектором.
Z_MODERATE = -1.0
Z_CRITICAL = -2.0

# --- пороги для сигналов движка по текущему ряду ---------------------------
# level_z и slope_z — robust z-score остатка и наклона. Их шкала шумнее нормы
# по истории, поэтому вниманием считаем отклонение уже от двух сигм.
Z_WATCH = 2.0
Z_STRONG = 3.5
SLOPE_Z_WATCH = 1.5
SLOPE_Z_STRONG = 2.5

# Соседние отклонения сливаются в один период, если разрыв между ними не больше
# этого числа суток. Иначе облачная неделя посреди засухи разрезала бы одно
# событие на два.
MERGE_GAP_DAYS = 12

# Событие должно опираться минимум на две точки: одна точка — это выброс.
MIN_POINTS = 2
MIN_DURATION_DAYS = 5

# Порог корреляции между фактической кривой сезона и климатической нормой поля.
# Ниже него считаем, что сезон не совпал с историей по форме — вероятна смена
# культуры в севообороте. Значение выбрано по замеру на четырёх полях двух
# регионов: 0.93 и 0.97 у полей, повторяющих свою норму, против 0.55 и 0.69
# у полей со сменой культуры. Выборка мала, порог подлежит уточнению.
PHASE_MISMATCH_CORRELATION = 0.75
MIN_POINTS_FOR_CORRELATION = 6

# Нижние границы масштаба отклонения, в единицах NDVI. Без них робастный
# z-score считается от собственного шума ряда: у гладкой кривой остаток от
# базовой линии равен машинному нулю, MAD стремится к нулю вместе с ним, и любое
# колебание в пятнадцатом знаке превращается в z порядка тысяч — здоровый сезон
# получает критические аномалии. Это та же причина, по которой в климатологии
# есть `MIN_STD`, и границы заданы так же — в физической величине, а не в сигмах:
# отклонение NDVI меньше 0.03 неотличимо от погрешности расчёта индекса,
# а суточное изменение меньше 0.005 — обычный ход вегетации.
MIN_RESIDUAL_SCALE = 0.03
MIN_SLOPE_SCALE = 0.005

# --- устойчивая просадка уровня ------------------------------------------
# Базовая линия LOWESS симметрична и потому идёт за самой аномалией: если поле
# просело на месяц, сглаженная кривая просядет вместе с ним, остаток внутри
# просадки обнулится, и видны останутся только её края. Для длительных событий
# уровня нужен причинный признак — сравнение уровня «до» с уровнем «после».
#
# Он же отделяет настоящую потерю вегетации от недомаскированного облака:
# облако роняет одну дату, и следующий снимок возвращается на прежний уровень,
# а потеря массы держится. Поэтому оба окна берутся медианой, а не значением
# в точке: одиночный провал медиану следующих двух недель не сдвигает.
DROP_PRE_WINDOW_DAYS = 14
DROP_POST_WINDOW_DAYS = 14

# Просадка ниже этого порога событием не считается. Отделяет угнетение от
# нормального созревания: у здорового сезона разница медиан двух соседних
# двухнедельных окон на спаде составляет около 0.17 NDVI, поэтому порог
# заметно выше. Величина абсолютная, в единицах NDVI: в долях сигмы её
# задать нельзя — разброс ряда сам зависит от того, была ли просадка.
DROP_WATCH = 0.22
DROP_STRONG = 0.45

# Доля просадки, при возврате выше которой событие считается законченным.
DROP_RECOVERY_FRACTION = 0.5

# Параметры движка по текущему ряду.
MAX_INTERP_GAP_DAYS = 14
LOWESS_FRAC = 0.2
SLOPE_WINDOW_DAYS = 14
PELT_PENALTY = 4.0
CHANGE_POINT_HALO_DAYS = 7
PERSISTENCE_WINDOW_DAYS = 10

# Когда истории нет, событие флагируется по единому баллу. Пороги балла для
# no-history пути и для отнесения события к критическому.
FLAG_SCORE_THRESHOLD = 45.0
CRITICAL_SCORE = 70.0

# Веса компонент anomaly_score. Историческая компонента и глубина отклонения
# важнее сопутствующих наклона и перелома. Наборы разные для случаев с историей
# и без неё, но каждый нормирован к сумме 1.0, поэтому балл сопоставим.
_WEIGHTS_WITH_HISTORY = {
    "history": 0.35,
    "level": 0.20,
    "slope": 0.15,
    "change": 0.10,
    "persistence": 0.20,
}
_WEIGHTS_NO_HISTORY = {
    "level": 0.35,
    "slope": 0.25,
    "change": 0.15,
    "persistence": 0.25,
}


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
class _Signal:
    """Значения сигналов движка в конкретную дату ряда."""

    anomaly_score: float
    level_z: float | None
    slope_z: float | None
    historical_z: float | None
    change_point_nearby: bool
    # Глубина устойчивой просадки уровня, NDVI. Ноль — просадки нет.
    drop: float = 0.0


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
    # Единый балл 0..100 от движка. Не путать с доверием: это глубина и
    # устойчивость отклонения, а не надёжность вывода.
    anomaly_score: float = 0.0
    # Сигналы движка в пиковой точке события. historical_z заполняется только
    # при наличии истории поля.
    level_z: float | None = None
    slope_z: float | None = None
    historical_z: float | None = None
    change_point_nearby: bool = False


def detect(
    samples: list[SeriesSample],
    climatology: Climatology,
    sowing_date: date | None = None,
    crop: str | None = None,
) -> tuple[list[AnomalyPeriod], dict[date, float]]:
    """Найти аномальные периоды и вернуть z-score по датам.

    `sowing_date` принимается для единообразия вызова, но на расчёт фазы
    не влияет — см. докстроку `analytics.climatology`.

    `crop` — культура текущего сезона. На числа она не влияет: норма строится
    по собственной истории поля, а не по справочнику культур. Влияет она на
    формулировку — расхождение с нормой имеет смысл называть вместе с тем,
    что на поле заявлено, иначе читателю не с чем сопоставить севооборот.

    В отличие от прежней версии, отсутствие истории поля больше не означает
    пустой результат: движок по текущему ряду работает и без нормы.
    """
    ordered = sorted(samples, key=lambda s: s.date)
    if not ordered:
        return [], {}

    signals = _engine_signals(ordered, climatology)

    if climatology.available:
        return _detect_with_history(ordered, signals, climatology, crop)
    return _detect_without_history(ordered, signals)


# ----------------------------------------------------------------------
# Путь с историей: климатология решает, движок обогащает
# ----------------------------------------------------------------------


def _detect_with_history(
    samples: list[SeriesSample],
    signals: dict[date, _Signal],
    climatology: Climatology,
    crop: str | None,
) -> tuple[list[AnomalyPeriod], dict[date, float]]:
    """Флаг события — отклонение от собственной нормы поля ниже −1.

    Это ровно правило прежнего детектора: на полях с историей поведение и
    границы событий не меняются, а `anomaly_score` и сигналы движка добавляются
    как обогащение вывода.
    """
    zscores: dict[date, float] = {}
    flagged: list[tuple[SeriesSample, float]] = []

    for sample in samples:
        z = climatology.zscore(phase_of(sample.date), sample.ndvi)
        if z is None:
            continue
        zscores[sample.date] = round(z, 4)
        if z < Z_MODERATE:
            flagged.append((sample, z))

    # Сезон мог целиком не совпасть с нормой по фазе. Тогда найденные
    # отклонения — артефакт сравнения с другой культурой, а не угнетение.
    mismatch, correlation = detect_phase_mismatch(samples, climatology)

    periods: list[AnomalyPeriod] = []
    for group in _group(flagged):
        period = _build_period(group, signals, use_history=True)
        if period is None:
            continue
        period.factors["curve_correlation"] = correlation
        if mismatch:
            period.phase_mismatch = True
            period.factors["phase_mismatch"] = True
            period.factors.setdefault("hypotheses", []).insert(
                0, _mismatch_hypothesis(crop)
            )
        periods.append(period)

    periods.sort(key=lambda p: (p.max_zscore, -p.duration_days))
    return periods, zscores


# ----------------------------------------------------------------------
# Путь без истории: событие решает движок по текущему ряду
# ----------------------------------------------------------------------


def _detect_without_history(
    samples: list[SeriesSample],
    signals: dict[date, _Signal],
) -> tuple[list[AnomalyPeriod], dict[date, float]]:
    """Нормы нет — событием считаем устойчивую просадку собственного ряда.

    Без истории «ниже нормы» неопределимо: сравнивать не с чем. Здесь событие —
    это устойчивое падение уровня относительно того, каким поле было до него,
    либо резкий провал относительно собственной плавной динамики сезона.

    Чего этот путь принципиально не умеет — заметить, что весь сезон целиком
    прошёл ниже обычного. Такой вывод требует знания, каким «обычный» был,
    то есть истории. Сервис обязан не выдавать это молчаливое ограничение
    за отсутствие проблем.
    """
    zscores: dict[date, float] = {}
    flagged: list[tuple[SeriesSample, float]] = []

    for sample in samples:
        signal = signals.get(sample.date)
        if signal is None:
            continue
        level_z = signal.level_z
        if level_z is not None and np.isfinite(level_z):
            zscores[sample.date] = round(float(level_z), 4)

        # Событие открывает только устойчивая просадка уровня. Отклонение
        # от базовой линии, наклон и переломы в балл входят и объясняют
        # событие, но сами по себе его не создают — и это не осторожность
        # ради осторожности. Замер на синтетическом здоровом сезоне с шумом
        # 0.02-0.06 NDVI (обычная величина после маскирования облаков): если
        # позволить открывать событие по остатку, ложное событие возникает
        # в 28-72% сезонов, потому что при таком шуме |z| легко переходит 2.
        # Просадка считается по медианам двух двухнедельных окон и к точечному
        # шуму нечувствительна: настоящий обвал она находит в 25 случаях из 25.
        if signal.drop >= DROP_WATCH:
            # Глубину переводим в ту же шкалу, что и остаток, чтобы сортировка
            # событий и порог критичности не зависели от того, каким сигналом
            # событие найдено.
            flagged.append((sample, -signal.drop / MIN_RESIDUAL_SCALE))

    periods: list[AnomalyPeriod] = []
    for group in _group(flagged):
        period = _build_period(group, signals, use_history=False)
        if period is not None:
            periods.append(period)

    periods.sort(key=lambda p: (p.max_zscore, -p.duration_days))
    return periods, zscores


# ----------------------------------------------------------------------
# Группировка и построение периода
# ----------------------------------------------------------------------


def _group(
    flagged: list[tuple[SeriesSample, float]],
) -> list[list[tuple[SeriesSample, float]]]:
    """Слить соседние отклонения в группы."""
    groups: list[list[tuple[SeriesSample, float]]] = []
    for item in flagged:
        if groups and (item[0].date - groups[-1][-1][0].date).days <= MERGE_GAP_DAYS:
            groups[-1].append(item)
        else:
            groups.append([item])
    return groups


def _build_period(
    group: list[tuple[SeriesSample, float]],
    signals: dict[date, _Signal],
    *,
    use_history: bool,
) -> AnomalyPeriod | None:
    samples = [sample for sample, _ in group]
    zs = [z for _, z in group]

    start, end = samples[0].date, samples[-1].date
    duration = (end - start).days + 1

    if len(group) < MIN_POINTS and duration < MIN_DURATION_DAYS:
        return None

    restored = sum(1 for s in samples if s.value_type == ValueType.RESTORED)
    restored_fraction = restored / len(samples)

    # Пик события — точка самого глубокого отклонения. По ней берём сигналы
    # движка для карточки события.
    peak_index = int(np.argmin(zs))
    peak_signal = signals.get(samples[peak_index].date)

    group_signals = [signals[s.date] for s in samples if s.date in signals]
    anomaly_score = max((sig.anomaly_score for sig in group_signals), default=0.0)
    change_point_nearby = any(sig.change_point_nearby for sig in group_signals)

    max_z = min(zs)
    if use_history:
        severity = (
            AnomalySeverity.CRITICAL if max_z < Z_CRITICAL else AnomalySeverity.MODERATE
        )
        historical_z = round(max_z, 4)
    else:
        severity = (
            AnomalySeverity.CRITICAL
            if anomaly_score >= CRITICAL_SCORE
            else AnomalySeverity.MODERATE
        )
        historical_z = None

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
        anomaly_score=round(float(anomaly_score), 2),
        level_z=_round_or_none(peak_signal.level_z if peak_signal else None),
        slope_z=_round_or_none(peak_signal.slope_z if peak_signal else None),
        historical_z=historical_z,
        change_point_nearby=change_point_nearby,
    )


def _round_or_none(value: float | None) -> float | None:
    if value is None or not np.isfinite(value):
        return None
    return round(float(value), 4)


# ----------------------------------------------------------------------
# Факторы и гипотезы
# ----------------------------------------------------------------------


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


def _mismatch_hypothesis(crop: str | None) -> str:
    """Пояснение к расхождению сезона с собственной нормой поля.

    Норма собрана по прошлым сезонам этого же участка, и культура в них могла
    быть другой. Поэтому заявленная культура здесь не доказательство, а точка
    отсчёта: читатель видит, что сравнивается, и может проверить севооборот.
    """
    if crop:
        return (
            f"динамика поля не совпадает с его историей: в этом сезоне заявлена культура "
            f"«{crop}», а норма построена по прошлым сезонам этого же поля — отклонение "
            "может объясняться севооборотом или другими сроками сева, а не угнетением"
        )
    return (
        "динамика поля не совпадает с его историей: вероятна смена культуры "
        "в севообороте или другие сроки сева, а не угнетение растительности"
    )


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


# ----------------------------------------------------------------------
# Движок: суточная сетка, LOWESS, робастные z, наклон, переломы, балл
# ----------------------------------------------------------------------


def _engine_signals(
    samples: list[SeriesSample], climatology: Climatology
) -> dict[date, _Signal]:
    """Посчитать сигналы движка и вернуть их по датам исходных точек.

    Сетка суточная и внутренняя: сигналы (baseline, наклон, переломы, балл)
    считаются на ней, но решение о событии принимается по исходным точкам ряда,
    а не по дорисованным дням. Так одиночный снимок-выброс, вокруг которого
    интерполяция создаёт узкую ложбину, остаётся одной точкой и событием не
    становится.
    """
    grid = _daily_grid(samples)
    if grid.empty or grid["ndvi_filled"].notna().sum() < 2:
        return {}

    grid["expected"] = _lowess_baseline(grid["date"], grid["ndvi_filled"], LOWESS_FRAC)
    grid["residual"] = grid["ndvi_filled"] - grid["expected"]
    grid["level_z"] = _robust_z(grid["residual"], MIN_RESIDUAL_SCALE)

    grid["slope"] = _rolling_slope(grid["ndvi_filled"], SLOPE_WINDOW_DAYS)
    grid["expected_slope"] = _rolling_slope(grid["expected"], SLOPE_WINDOW_DAYS)
    grid["slope_z"] = _robust_z(grid["slope"] - grid["expected_slope"], MIN_SLOPE_SCALE)

    grid["drop"] = _sustained_drop(grid["ndvi_filled"].to_numpy(float))

    change = _detect_change_points(grid["ndvi_filled"])
    grid["change_point_nearby"] = (
        pd.Series(change.astype(int))
        .rolling(CHANGE_POINT_HALO_DAYS, center=True, min_periods=1)
        .max()
        .astype(bool)
        .to_numpy()
    )

    has_history = climatology.available
    if has_history:
        grid["historical_z"] = [
            climatology.zscore(phase_of(day.date()), value)
            for day, value in zip(grid["date"], grid["ndvi_filled"])
        ]
    else:
        grid["historical_z"] = np.nan

    grid["anomaly_score"] = _score(grid, has_history)

    signals: dict[date, _Signal] = {}
    known = {sample.date for sample in samples}
    for _, row in grid.iterrows():
        day = row["date"].date()
        if day not in known:
            continue
        signals[day] = _Signal(
            anomaly_score=float(row["anomaly_score"]),
            level_z=_finite_or_none(row["level_z"]),
            slope_z=_finite_or_none(row["slope_z"]),
            historical_z=_finite_or_none(row["historical_z"]),
            change_point_nearby=bool(row["change_point_nearby"]),
            drop=float(row["drop"]),
        )
    return signals


def _finite_or_none(value) -> float | None:
    value = float(value)
    return value if np.isfinite(value) else None


def _daily_grid(samples: list[SeriesSample]) -> pd.DataFrame:
    """Суточная сетка ряда с PCHIP-заполнением малых пропусков."""
    src = pd.DataFrame(
        {
            "date": [pd.Timestamp(s.date) for s in samples],
            "ndvi": [s.ndvi for s in samples],
            "is_restored": [s.value_type == ValueType.RESTORED for s in samples],
        }
    ).sort_values("date")

    daily = pd.DataFrame(
        {"date": pd.date_range(src["date"].min(), src["date"].max(), freq="D")}
    ).merge(src, on="date", how="left")

    known = daily["ndvi"].notna()
    if known.sum() < 2:
        daily["ndvi_filled"] = daily["ndvi"]
        return daily

    x = np.arange(len(daily), dtype=float)
    x_known = x[known.to_numpy()]
    y_known = daily.loc[known, "ndvi"].to_numpy(float)

    interpolator = PchipInterpolator(x_known, y_known, extrapolate=False)
    candidate = interpolator(x)

    known_idx = np.where(known.to_numpy())[0]
    allow = known.to_numpy().copy()
    for left, right in zip(known_idx[:-1], known_idx[1:]):
        if right - left - 1 <= MAX_INTERP_GAP_DAYS:
            allow[left : right + 1] = True

    filled = daily["ndvi"].to_numpy(float).copy()
    use_interp = (~known.to_numpy()) & allow & np.isfinite(candidate)
    filled[use_interp] = candidate[use_interp]
    daily["ndvi_filled"] = np.clip(filled, -1.0, 1.0)
    return daily


def _lowess_baseline(dates: pd.Series, values: pd.Series, frac: float) -> pd.Series:
    x = (pd.to_datetime(dates) - pd.to_datetime(dates).min()).dt.days.to_numpy(float)
    y = values.to_numpy(float)
    mask = np.isfinite(y)

    if mask.sum() < 8 or _sm_lowess is None:
        # Мало точек или нет statsmodels — грубая, но устойчивая оценка.
        return pd.Series(y, index=values.index).rolling(
            15, center=True, min_periods=3
        ).median()

    smoothed = _sm_lowess(endog=y[mask], exog=x[mask], frac=frac, it=2, return_sorted=False)
    result = np.interp(x, x[mask], smoothed)
    return pd.Series(result, index=values.index)


def _robust_z(values: pd.Series, min_scale: float) -> pd.Series:
    """Робастный z-score через MAD с нижней границей масштаба.

    Граница обязательна: у ряда, который хорошо описывается своей же плавной
    кривой, разброс остатка вырождается, и деление на него превращает шум
    в аномалию. `min_scale` задаётся в единицах измеряемой величины и означает
    «меньше этого отклонение не считается отклонением вовсе».
    """
    arr = values.astype(float).to_numpy()
    finite = np.isfinite(arr)
    out = np.full(len(arr), np.nan, dtype=float)

    if finite.sum() < 5:
        return pd.Series(out, index=values.index)

    x = arr[finite]
    med = np.median(x)
    mad = np.median(np.abs(x - med))

    # 1.4826 = 1/Φ⁻¹(0.75): переводит MAD в оценку стандартного отклонения.
    scale = max(1.4826 * mad, min_scale)
    out[finite] = (x - med) / scale

    return pd.Series(out, index=values.index)


def _rolling_slope(series: pd.Series, window_days: int) -> pd.Series:
    y = series.astype(float)
    result = np.full(len(y), np.nan)
    half = max(2, window_days // 2)

    for i in range(len(y)):
        left = max(0, i - half)
        right = min(len(y), i + half + 1)
        vals = y.iloc[left:right].to_numpy()
        mask = np.isfinite(vals)
        if mask.sum() < 4:
            continue

        xx = np.arange(left, right, dtype=float)[mask]
        yy = vals[mask]
        xx = xx - xx.mean()
        denom = np.sum(xx * xx)
        if denom < EPS:
            continue
        result[i] = np.sum(xx * (yy - yy.mean())) / denom

    return pd.Series(result, index=series.index)


def _sustained_drop(values: np.ndarray) -> np.ndarray:
    """Глубина устойчивой просадки уровня по дням суточной сетки.

    Просадкой считается переход, после которого поле держится ниже, чем можно
    было ожидать по его же предыдущему ходу. Ожидание строится продолжением
    тренда двух предыдущих недель, и это ключевая часть: осенью NDVI падает
    у любого здорового поля, и сравнение «уровень после против уровня до» без
    поправки на уже идущее снижение объявило бы созревание аномалией. Продолжив
    тренд, мы спрашиваем не «стало ли ниже», а «стало ли ниже, чем поле само
    себе обещало».

    Растущий тренд вперёд не продолжается: остановка роста — не потеря массы,
    и требовать от поля продолжения разгона мы не вправе.

    Найденная просадка распространяется вперёд до восстановления — иначе
    событием оказался бы только день перелома, а не весь период угнетения:
    в середине просадки сравнивать уже не с чем, предыдущие две недели к тому
    моменту сами лежат внутри события.

    Возвращает массив глубин: ноль там, где просадки нет.
    """
    n = len(values)
    magnitude = np.zeros(n, dtype=float)
    if n < DROP_PRE_WINDOW_DAYS + 2:
        return magnitude

    # Медианы окон относятся к их серединам, поэтому ожидание переносится
    # на расстояние между серединами, а не на длину окна.
    offset = (DROP_PRE_WINDOW_DAYS + DROP_POST_WINDOW_DAYS) / 2.0

    index = DROP_PRE_WINDOW_DAYS
    while index < n:
        before = values[max(0, index - DROP_PRE_WINDOW_DAYS) : index]
        after = values[index : min(n, index + DROP_POST_WINDOW_DAYS)]
        if before.size == 0 or after.size == 0:
            break

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            level_before = np.nanmedian(before)
            level_after = np.nanmedian(after)

        # Только снижение продолжаем вперёд: рост не экстраполируем.
        trend = min(_linear_slope(before), 0.0)
        expected_after = level_before + trend * offset

        drop = float(expected_after - level_after)
        if not np.isfinite(drop) or drop < DROP_WATCH:
            index += 1
            continue

        # Переход занимает время, и на самой дате перелома поле обычно ещё
        # не внизу: спутник снимает раз в несколько суток, а суточная сетка
        # между снимками интерполирована. Поэтому начало события ищется там,
        # где уровень действительно опустился, а не там, где перелом замечен.
        recovery = expected_after - DROP_RECOVERY_FRACTION * drop
        limit = min(n, index + DROP_POST_WINDOW_DAYS)

        start = index
        while start < limit and not (
            np.isfinite(values[start]) and values[start] < recovery
        ):
            start += 1
        if start >= limit:
            index += 1
            continue

        # Событие держится, пока поле не вернулось к части утраченного уровня.
        end = start
        while end < n and (not np.isfinite(values[end]) or values[end] < recovery):
            end += 1

        magnitude[start:end] = np.maximum(magnitude[start:end], drop)
        index = max(end, index + 1)

    return magnitude


def _linear_slope(values: np.ndarray) -> float:
    """Наклон ряда по методу наименьших квадратов, единиц в сутки."""
    mask = np.isfinite(values)
    if mask.sum() < 4:
        return 0.0

    x = np.arange(len(values), dtype=float)[mask]
    y = values[mask]
    x = x - x.mean()
    denom = float(np.sum(x * x))
    if denom < EPS:
        return 0.0
    return float(np.sum(x * (y - y.mean())) / denom)


def _detect_change_points(series: pd.Series) -> np.ndarray:
    mask = np.zeros(len(series), dtype=bool)
    if rpt is None:
        return mask

    y = series.astype(float).to_numpy()
    if np.isfinite(y).sum() < 20:
        return mask

    signal = pd.Series(y).interpolate(limit_direction="both").to_numpy().reshape(-1, 1)
    try:
        breakpoints = rpt.Pelt(model="rbf").fit(signal).predict(pen=PELT_PENALTY)
        for bp in breakpoints[:-1]:
            idx = max(0, min(len(mask) - 1, bp - 1))
            mask[idx] = True
    except Exception as exc:  # pragma: no cover - защита от сбоя ruptures
        warnings.warn(f"PELT failed: {exc}")

    return mask


def _score(grid: pd.DataFrame, has_history: bool) -> pd.Series:
    """Свести сигналы в единый балл 0..100 по датам суточной сетки."""
    level_z = grid["level_z"].to_numpy(float)
    slope_z = grid["slope_z"].to_numpy(float)
    historical_z = grid["historical_z"].to_numpy(float)
    change = grid["change_point_nearby"].to_numpy(bool)
    drop = grid["drop"].to_numpy(float)

    # Глубина отклонения вниз от собственной плавной кривой сезона. Она видит
    # быстрые провалы, но слепа к длительным: базовая линия уходит за ними
    # следом. Поэтому берётся вместе с просадкой уровня — что сильнее, то и
    # определяет компоненту.
    level_comp = np.maximum(
        _ramp(-np.nan_to_num(level_z), Z_WATCH, Z_STRONG),
        _ramp(drop, DROP_WATCH, DROP_STRONG),
    )
    # Ухудшение наклона относительно ожидаемого хода.
    slope_comp = _ramp(-np.nan_to_num(slope_z), SLOPE_Z_WATCH, SLOPE_Z_STRONG)
    change_comp = change.astype(float)

    if has_history:
        # Историческая компонента: насколько поле хуже собственной нормы в эту
        # фазу. Порог из постановки: −1 внимание, −2 критично.
        history_comp = _ramp(-np.nan_to_num(historical_z), -Z_MODERATE, -Z_CRITICAL)
        negative = (historical_z < Z_MODERATE) | (level_z < -Z_WATCH)
    else:
        history_comp = np.zeros(len(grid))
        negative = (level_z < -Z_WATCH) | (drop >= DROP_WATCH)

    persistence_comp = (
        pd.Series(np.nan_to_num(negative.astype(float)))
        .rolling(PERSISTENCE_WINDOW_DAYS, center=True, min_periods=1)
        .mean()
        .to_numpy()
    )

    weights = _WEIGHTS_WITH_HISTORY if has_history else _WEIGHTS_NO_HISTORY
    raw = (
        weights.get("history", 0.0) * history_comp
        + weights["level"] * level_comp
        + weights["slope"] * slope_comp
        + weights["change"] * change_comp
        + weights["persistence"] * persistence_comp
    )
    return pd.Series(np.clip(100.0 * raw, 0.0, 100.0), index=grid.index)


def _ramp(value: np.ndarray, low: float, high: float) -> np.ndarray:
    """Линейно перевести значение из [low, high] в [0, 1] с отсечением."""
    return np.clip((value - low) / max(high - low, EPS), 0.0, 1.0)
