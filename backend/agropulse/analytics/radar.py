"""Аналитика радарного ряда Sentinel-1.

Радар в этом сервисе — не ещё один «индекс здоровья», а независимое
подтверждение. Оптика измеряет спектральное состояние листа, радар — структуру
полога и поверхность почвы. Механизмы измерения разные, поэтому совпадение
события в обоих источниках означает гораздо больше, чем удвоенное количество
графиков.

Отсюда три ограничения, которые соблюдаются во всём модуле.

Первое: сравнивать можно только снимки одной орбиты. Угол падения луча
у восходящего и нисходящего пролёта разный, и уровень сигнала различается
на величину, сопоставимую с настоящими событиями на поле. Все разности
считаются внутри одного относительного номера орбиты, разрыв между орбитами
разностью не является.

Второе: радар сам по себе причину не называет. Падение VH одинаково выглядит
при уборке, полегании, скашивании и естественном завершении вегетации.
Формулировки в этом модуле — гипотезы с перечнем возможных причин, и такими
они должны доехать до пользователя.

Третье: абсолютных величин радар не даёт. Влажность почвы в процентах требует
калибровки по типу почвы и наземных измерений, поэтому здесь считаются только
изменения относительно собственной истории поля.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date, timedelta

import numpy as np

from agropulse.analytics import climatology as climatology_module

logger = logging.getLogger(__name__)

# Изменение сигнала растительности, которое считаем существенным, дБ.
# Меньшие колебания сопоставимы с остаточным спеклом и разбросом условий съёмки.
SIGNIFICANT_CHANGE_DB = 1.5

# Для сигнала поверхности порог выше, и это не осторожность, а физика.
# VV определяется влажностью и шероховатостью верхнего слоя почвы, поэтому
# на голой почве и разреженных всходах он ходит на 2-3 дБ от одного дождя.
# Замер на поле кукурузы в Айове: по порогу 1,5 дБ за сезон набирается семь
# «изменений поверхности», по порогу 3 дБ остаются три — те, что действительно
# выделяются на фоне обычных колебаний этого поля.
SURFACE_CHANGE_DB = 3.0

# Сколько разностей нужно накопить, чтобы говорить о резкости перехода
# «по меркам этого поля». На меньшей выборке ранг не информативен.
MIN_DELTAS_FOR_SCORE = 8

# Максимальный разрыв между соседними снимками одной орбиты, при котором
# разность ещё осмысленна. Период повторения Sentinel-1 — 6-12 суток;
# разрыв в полтора месяца означает пропуск, а не изменение за один шаг.
MAX_DELTA_GAP_DAYS = 30

# Насколько окно аномалии может выходить за свои границы при поиске
# радарного подтверждения. Пролёты Sentinel-1 и Sentinel-2 не совпадают,
# и точного совпадения дат ждать нельзя.
CONFIRMATION_WINDOW_DAYS = 7

# Порог z-score радарного сигнала, ниже которого считаем, что радар
# подтверждает угнетение.
RADAR_CONFIRMATION_Z = -1.0

# Какую долю скачка должен отыграть следующий снимок, чтобы изменение
# считалось откатившимся, а не состоявшимся.
#
# Порог существует не для красоты. На голой почве и разреженных всходах
# обратное рассеяние определяется влажностью верхнего слоя, а не
# растительностью: после дождя сигнал уходит на несколько децибел и через
# неделю возвращается. Замер на реальном поле кукурузы в Айове дал в апреле
# и мае шесть таких скачков величиной 4-7 дБ подряд — по порогу в децибелах
# все они выглядели бы уборкой. Настоящее структурное изменение (уборка,
# полегание) необратимо, поэтому событием считается только то изменение,
# которое удержалось на следующей съёмке той же орбиты.
REVERSION_FRACTION = 0.4


@dataclass(slots=True)
class RadarSample:
    """Точка радарного ряда, поданная на анализ."""

    date: date
    orbit_direction: str | None = None
    relative_orbit: int | None = None
    vv_median_db: float | None = None
    vh_median_db: float | None = None
    rvi_median: float | None = None
    vh_vv_difference_db: float | None = None
    spatial_iqr_db: float | None = None
    low_signal_fraction: float | None = None
    valid_fraction: float | None = None


@dataclass(slots=True)
class RadarEvent:
    """Резкое изменение радарного сигнала.

    Причина не называется: одно и то же изменение возможно по нескольким
    причинам, и выбрать между ними радар не может.
    """

    date: date
    kind: str
    magnitude_db: float
    score: float | None
    title: str
    hypotheses: list[str] = dataclass_field(default_factory=list)
    # Удержался ли новый уровень на следующей съёмке той же орбиты.
    # У последнего снимка ряда проверить нечем — такое событие показывается,
    # но помечается как неподтверждённое.
    confirmed: bool = True


# Вердикт радара по окну события.
RADAR_AGREES = "agrees"        # радар показывает согласованное изменение
RADAR_SILENT = "silent"        # снимки в окне есть, изменений не видно
RADAR_NO_DATA = "no_data"      # снимков в окне нет, проверить нечем


@dataclass(slots=True)
class Corroboration:
    """Подтверждённость события независимыми источниками."""

    score: int
    level: str
    # Что именно сказал радар. Отдельно от балла, потому что низкий балл
    # получается по двум совершенно разным причинам, и путать их опасно:
    # «радар в окне есть и изменений не показывает» — повод усомниться
    # в событии, «радарных снимков в окне нет» — повод усомниться только
    # в собственной осведомлённости. Второе особенно важно не занижать:
    # подтверждённость проседает от облачности, то есть ровно тогда,
    # когда оптика слабее всего и смотреть надо больше, а не меньше.
    radar_verdict: str = RADAR_NO_DATA
    parts: dict[str, int] = dataclass_field(default_factory=dict)
    notes: list[str] = dataclass_field(default_factory=list)


# ---------------------------------------------------------------------------
# Производные величины ряда
# ---------------------------------------------------------------------------


def derive(samples: list[RadarSample]) -> dict[date, dict]:
    """Разности между соседними снимками и резкость перехода.

    Разность берётся к предыдущему снимку **той же орбиты**, а не просто
    к предыдущей дате. Иначе смена геометрии съёмки выглядела бы как событие
    на поле — самая частая ошибка при работе с Sentinel-1.
    """
    by_orbit: dict[tuple, list[RadarSample]] = {}
    for sample in samples:
        key = (sample.orbit_direction, sample.relative_orbit)
        by_orbit.setdefault(key, []).append(sample)

    derived: dict[date, dict] = {}
    all_vh_deltas: list[float] = []

    for orbit_samples in by_orbit.values():
        ordered = sorted(orbit_samples, key=lambda item: item.date)
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if (current.date - previous.date).days > MAX_DELTA_GAP_DAYS:
                continue
            values = {
                "vv_change_db": _difference(current.vv_median_db, previous.vv_median_db, 3),
                "vh_change_db": _difference(current.vh_median_db, previous.vh_median_db, 3),
                "rvi_change": _difference(current.rvi_median, previous.rvi_median, 4),
            }
            derived[current.date] = values
            if values["vh_change_db"] is not None:
                all_vh_deltas.append(abs(values["vh_change_db"]))

    # Резкость перехода измеряется в рангах собственной истории поля:
    # у поля под многолетними травами и у поля под пропашной культурой
    # «обычная» величина скачка разная, и общего порога в децибелах нет.
    if len(all_vh_deltas) >= MIN_DELTAS_FOR_SCORE:
        reference = np.array(all_vh_deltas, dtype=float)
        for values in derived.values():
            delta = values.get("vh_change_db")
            if delta is None:
                continue
            values["change_point_score"] = round(
                float(np.mean(reference <= abs(delta))), 3
            )

    return derived


def _difference(current: float | None, previous: float | None, digits: int) -> float | None:
    if current is None or previous is None:
        return None
    return round(current - previous, digits)


# ---------------------------------------------------------------------------
# События
# ---------------------------------------------------------------------------


def detect_events(samples: list[RadarSample], derived: dict[date, dict]) -> list[RadarEvent]:
    """Найти резкие изменения радарного сигнала.

    Событие — не диагноз. Каждому изменению сопоставляется перечень возможных
    причин, а выбор между ними требует оптики, погоды и знания агротехники.

    Рост сигнала событием не считается — по той же причине, по которой им не
    считается рост NDVI: это нормальное развитие покрова, а не повод ехать
    в поле. Он виден на графике и в ряду.

    Каждое изменение проверяется следующей съёмкой той же орбиты: откатившийся
    скачок означает погоду, а не событие на поле.
    """
    events: list[RadarEvent] = []
    next_change = _next_change_by_orbit(samples, derived)

    for sample in sorted(samples, key=lambda item: item.date):
        values = derived.get(sample.date)
        if not values:
            continue

        vh_change = values.get("vh_change_db")
        vv_change = values.get("vv_change_db")
        score = values.get("change_point_score")

        if vh_change is not None and vh_change <= -SIGNIFICANT_CHANGE_DB:
            state = _confirmation(vh_change, next_change.get((sample.date, "vh")))
            if state is False:
                continue
            events.append(
                RadarEvent(
                    date=sample.date,
                    kind="vegetation_drop",
                    magnitude_db=vh_change,
                    score=score,
                    title="Резкое снижение радарного сигнала растительности",
                    hypotheses=[
                        "уборка или скашивание",
                        "полегание",
                        "потеря растительной массы",
                        "естественное завершение вегетации",
                    ],
                    confirmed=state is True,
                )
            )
            continue

        # Поверхность меняется тогда, когда сигнал почвы сдвинулся,
        # а сигнал растительности остался прежним.
        if vv_change is not None and abs(vv_change) >= SURFACE_CHANGE_DB:
            state = _confirmation(vv_change, next_change.get((sample.date, "vv")))
            if state is False:
                continue
            rising = vv_change > 0
            events.append(
                RadarEvent(
                    date=sample.date,
                    kind="surface_change",
                    magnitude_db=vv_change,
                    score=score,
                    title="Резкое изменение состояния поверхности поля",
                    hypotheses=(
                        ["увлажнение после осадков или полива", "агротехническая операция"]
                        if rising
                        else ["пересыхание поверхности", "изменение шероховатости после обработки"]
                    ),
                    confirmed=state is True,
                )
            )

    return events


def _next_change_by_orbit(
    samples: list[RadarSample], derived: dict[date, dict]
) -> dict[tuple[date, str], float | None]:
    """Изменение на следующей съёмке той же орбиты, по каждой дате.

    `None` означает, что следующей съёмки этой орбиты в ряду нет и проверить
    удержание уровня нечем.
    """
    by_orbit: dict[tuple, list[date]] = {}
    for sample in samples:
        key = (sample.orbit_direction, sample.relative_orbit)
        by_orbit.setdefault(key, []).append(sample.date)

    result: dict[tuple[date, str], float | None] = {}
    for dates in by_orbit.values():
        ordered = sorted(dates)
        for current, following in zip(ordered, ordered[1:], strict=False):
            values = derived.get(following) or {}
            result[(current, "vh")] = values.get("vh_change_db")
            result[(current, "vv")] = values.get("vv_change_db")
    return result


def _confirmation(change: float, following: float | None) -> bool | None:
    """Удержался ли новый уровень на следующей съёмке.

    Возвращает `True` — удержался, `False` — откатился, `None` — проверить
    нечем: следующей съёмки этой орбиты в ряду нет.
    """
    if following is None:
        return None
    reverted = following * change < 0 and abs(following) >= REVERSION_FRACTION * abs(change)
    return not reverted



# ---------------------------------------------------------------------------
# Подтверждённость события
# ---------------------------------------------------------------------------

# Вклад каждого источника. Величины взяты как есть из принятой схемы оценки:
# оптика весит больше радара, потому что напрямую измеряет состояние
# растительности, а радар отвечает на смежный вопрос о структуре.
WEIGHT_OPTICAL = 30
WEIGHT_OPTICAL_RESTORED = 15
WEIGHT_RADAR = 20
WEIGHT_PERSISTENCE = 20
WEIGHT_WEATHER = 20
PENALTY_CLOUDS = -20
PENALTY_MIXED_ORBIT = -20

# Зарезервировано под пространственное совпадение аномалий в оптике и радаре.
# Пока всегда ноль: попиксельный анализ не реализован, см. docs/PLAN.md.
# Из-за этого достижимый максимум равен 90, а не 100, и это осознанно:
# «идеально подтверждённого» события у нас пока не бывает.
WEIGHT_SPATIAL = 10

LEVEL_THRESHOLDS = ((70, "high"), (40, "possible"), (0, "weak"))

# Доля восстановленных точек, выше которой событие считается скорее
# дорисованным моделью, чем измеренным.
MOSTLY_RESTORED = 0.5

# Доля закрытой облаками площади, выше которой оптический ряд в окне
# считается ненадёжным.
HEAVY_CLOUD_FRACTION = 0.5


def corroborate(
    *,
    start_date: date,
    end_date: date,
    observed_points: int,
    restored_fraction: float | None,
    cloud_fraction: float | None,
    weather_hypotheses: list[str],
    samples: list[RadarSample],
    events: list[RadarEvent] | None = None,
) -> Corroboration:
    """Оценить, насколько событие подтверждено независимыми источниками.

    Оценка отвечает на другой вопрос, нежели `confidence` аномалии. Там —
    хватило ли данных, чтобы вообще посчитать событие. Здесь — сошлись ли
    на нём разные способы измерения. Событие может быть надёжно измерено
    одной оптикой и остаться неподтверждённым, и наоборот.
    """
    parts: dict[str, int] = {}
    notes: list[str] = []

    # --- оптика ---
    if restored_fraction is not None and restored_fraction > MOSTLY_RESTORED:
        parts["optical"] = WEIGHT_OPTICAL_RESTORED
        notes.append(
            f"больше половины точек периода ({restored_fraction:.0%}) восстановлены моделью, "
            "а не измерены"
        )
    else:
        parts["optical"] = WEIGHT_OPTICAL

    # --- устойчивость во времени ---
    if observed_points >= 2:
        parts["persistence"] = WEIGHT_PERSISTENCE
    else:
        notes.append("событие опирается на одну измеренную точку оптического ряда")

    # --- радар ---
    window = _window_samples(samples, start_date, end_date)
    confirmation = _radar_confirmation(
        samples, window, events or [], start_date, end_date
    )
    if confirmation is not None:
        radar_verdict = RADAR_AGREES
        parts["radar"] = WEIGHT_RADAR
        notes.append(confirmation)
    elif not window:
        radar_verdict = RADAR_NO_DATA
        notes.append("радарных снимков в окне события нет")
    else:
        radar_verdict = RADAR_SILENT
        notes.append("радар согласованного изменения не показывает")

    # --- погода ---
    if weather_hypotheses:
        parts["weather"] = WEIGHT_WEATHER

    # --- штрафы ---
    if cloud_fraction is not None and cloud_fraction >= HEAVY_CLOUD_FRACTION:
        parts["clouds"] = PENALTY_CLOUDS
        notes.append(f"оптический ряд в окне закрыт облаками на {cloud_fraction:.0%}")

    # Штраф не за сам факт нескольких орбит: сравнения между орбитами нигде
    # не делаются, ни в уровне, ни в разностях. Он за фрагментированную
    # доказательную базу — когда окно на вид плотное, но пригодной к сравнению
    # орбиты в нём одна съёмка, а остальное набрано пролётами, которые с ней
    # не сопоставимы. Подтверждение по одной точке слабое, и это должно быть
    # видно в оценке.
    if parts.get("radar") and len(window) > 1:
        orbit = _dominant_orbit(window)
        aligned = sum(
            1
            for sample in window
            if (sample.orbit_direction, sample.relative_orbit) == orbit
        )
        if aligned < 2:
            parts["mixed_orbit"] = PENALTY_MIXED_ORBIT
            notes.append(
                "в окне события лишь одна съёмка пригодной к сравнению орбиты, "
                "остальные принадлежат другим пролётам и с ней не сопоставимы"
            )

    score = max(0, min(100, sum(parts.values())))
    return Corroboration(
        score=score,
        level=_level(score),
        radar_verdict=radar_verdict,
        parts=parts,
        notes=notes,
    )


def _level(score: int) -> str:
    for threshold, name in LEVEL_THRESHOLDS:
        if score >= threshold:
            return name
    return "weak"


def _window_samples(
    samples: list[RadarSample], start_date: date, end_date: date
) -> list[RadarSample]:
    """Радарные снимки, попавшие в окно события.

    Границы расширены: пролёты Sentinel-1 и Sentinel-2 не совпадают, и требовать
    точного попадания даты означало бы почти всегда не находить подтверждения.
    """
    margin = timedelta(days=CONFIRMATION_WINDOW_DAYS)
    return [
        sample
        for sample in samples
        if start_date - margin <= sample.date <= end_date + margin
        and sample.vh_median_db is not None
    ]


def _radar_confirmation(
    samples: list[RadarSample],
    window: list[RadarSample],
    events: list[RadarEvent],
    start_date: date,
    end_date: date,
) -> str | None:
    """Подтверждает ли радар угнетение в окне события.

    Признаков два, и они отвечают на разные вопросы. Уровень относительно
    собственной нормы поля говорит «полог слабее обычного для этой фазы»;
    найденное событие — «структура резко изменилась именно тогда». Любого
    из них достаточно: поле могло войти в аномалию с запасом по уровню и
    всё равно резко просесть, и наоборот — держаться ниже нормы весь период
    без единого скачка.
    """
    if not window:
        return None

    margin = timedelta(days=CONFIRMATION_WINDOW_DAYS)
    inside = [
        event
        for event in events
        if event.kind == "vegetation_drop"
        and event.confirmed
        and start_date - margin <= event.date <= end_date + margin
    ]
    if inside:
        worst = min(inside, key=lambda event: event.magnitude_db)
        return (
            f"радар зафиксировал резкое снижение сигнала растительности "
            f"{worst.date.isoformat()} ({worst.magnitude_db:+.1f} дБ)"
        )

    orbit = _dominant_orbit(window)
    history = [
        (sample.date, sample.vh_median_db)
        for sample in samples
        if sample.vh_median_db is not None
        and (sample.orbit_direction, sample.relative_orbit) == orbit
    ]
    # Норма построена по одной орбите, значит и сравнивать с ней можно только
    # снимки той же орбиты. Иначе разница углов падения луча войдёт в z-score
    # как отклонение состояния поля.
    aligned = [
        sample
        for sample in window
        if (sample.orbit_direction, sample.relative_orbit) == orbit
    ]

    norm = climatology_module.build(
        history=history,
        target_dates=[sample.date for sample in aligned],
        sowing_date=None,
        exclude_year=window[0].date.year,
    )
    if norm.available:
        zscores = [
            z
            for sample in aligned
            if (z := norm.zscore(climatology_module.phase_of(sample.date), sample.vh_median_db))
            is not None
        ]
        if zscores:
            mean_z = float(np.mean(zscores))
            if mean_z <= RADAR_CONFIRMATION_Z:
                return (
                    f"радарный сигнал растительности ниже обычного для этого поля "
                    f"(z = {mean_z:.1f})"
                )
            return None

    # Запасной признак: истории на норму не хватило, смотрим на само падение —
    # снова внутри одной орбиты, разрыв между орбитами падением не является.
    drops = [
        sample
        for previous, sample in zip(aligned, aligned[1:], strict=False)
        if previous.vh_median_db - sample.vh_median_db >= SIGNIFICANT_CHANGE_DB
    ]
    if drops:
        return "радар показывает резкое снижение сигнала растительности внутри периода"
    return None


def _dominant_orbit(window: list[RadarSample]) -> tuple:
    """Орбита, к которой относится большинство снимков окна."""
    counts: dict[tuple, int] = {}
    for sample in window:
        key = (sample.orbit_direction, sample.relative_orbit)
        counts[key] = counts.get(key, 0) + 1
    return max(counts, key=lambda key: counts[key])
