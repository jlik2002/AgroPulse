"""Индекс потребности хозяйства в поддержке.

Оценка риска считается по полю (`analytics/risk.py`), а решение о поддержке
принимается по хозяйству. Этот модуль соединяет одно с другим и отвечает
на вопрос распорядителя средств: кого проверять первым.

Три решения, которые здесь приняты сознательно.

**Веса поля не пересчитываются.** Индекс хозяйства строится поверх готовых
баллов полей, а не по собственному набору факторов. Иначе прогноз ухудшения
вошёл бы в сумму дважды: он выведен из тех же отклонений от нормы, что и
текущая динамика, уже учтённая в балле поля.

**Поля без оценки не занижают балл.** Участок, по которому не набралось
наблюдений, в средневзвешенное не входит вовсе — иначе хозяйство, про которое
нечего сказать, оказалось бы в конце очереди, то есть система заявила бы
«поддержка не нужна» там, где она просто ничего не увидела. Их площадь
выносится отдельным показателем и понижает достоверность, а не балл.

**Одно критическое поле не растворяется в площади.** Средневзвешенное по
площади — правильная основа, но у неё есть ровно один способ солгать: поле
в 20 га с баллом 85 на хозяйстве в 800 га даёт вклад в два балла и исчезает.
Поэтому итог не опускается ниже доли от максимального балла отдельного поля:
одно поле в критическом состоянии — уже основание для проверки, даже если
остальная площадь в норме.

Балл нигде не хранится. Он считается на чтении по уже прочитанным строкам
полей и поэтому не может разойтись с ними: третьего места, где данные
протухают, не появляется.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from dataclasses import field as dataclass_field

from agropulse.analytics.trust import TRUST_CONFIRMED, TRUST_DISPUTED
from agropulse.db.models import (
    Anomaly,
    AnomalySeverity,
    Field,
    FieldStatus,
    ForecastRun,
)

# Надбавки к средневзвешенному риску, в баллах итоговой шкалы 0..100.
# Смысл — не «сделать число больше», а различить два хозяйства с одинаковым
# средним: там, где проблема сосредоточена в критических полях, выезд нужнее.
BONUS_CRITICAL_SHARE = 15.0
BONUS_PROBLEM_SHARE = 10.0

# Доля максимального балла отдельного поля, ниже которой хозяйство
# не опускается. 0,6 подобрано так, чтобы хозяйство с одним полем
# на пороге критического статуса (60) не выпадало из очереди на осмотр.
SINGLE_FIELD_FLOOR = 0.6

# Границы категорий совпадают с порогами статуса поля: реестр и карточка
# поля обязаны называть одно и то же состояние одинаково.
THRESHOLD_URGENT = 60.0
THRESHOLD_SUPPORT = 30.0

# Ниже этой доли оценённой площади заключение не выдаётся вовсе.
MIN_ASSESSED_SHARE = 0.5

# Границы достоверности. `confidence` приходит из оценки риска поля
# и уже учитывает плотность ряда, облачность и долю восстановленных точек.
TRUST_HIGH_SHARE, TRUST_HIGH_CONFIDENCE = 0.8, 0.6
TRUST_MEDIUM_SHARE, TRUST_MEDIUM_CONFIDENCE = 0.5, 0.35

# Статусы, при которых у поля есть балл и оно участвует в средневзвешенном.
ASSESSED_STATUSES = (FieldStatus.CRITICAL, FieldStatus.ATTENTION, FieldStatus.NORMAL)
PROBLEM_STATUSES = (FieldStatus.CRITICAL, FieldStatus.ATTENTION)


class ReviewCategory(str, enum.Enum):
    """Категория для комиссии.

    Формулировки намеренно не содержат решения о деньгах. Спутник видит
    угнетение растительности, а не основание для выплаты, и система вправе
    сказать только «рассмотреть в первую очередь» — распоряжается комиссия.
    """

    URGENT = "urgent"              # критическое устойчивое ухудшение
    SUPPORT = "support"            # умеренная подтверждённая аномалия
    CLARIFY = "clarify"            # отклонение есть, но не подтверждается
    MONITOR = "monitor"            # стабильное состояние
    UNDETERMINED = "undetermined"  # данных недостаточно для заключения


# Что категория означает и что предлагается сделать. Тексты живут рядом
# с правилом, а не в вёрстке: реестр, карточка хозяйства и PDF обязаны
# называть одно и то же состояние одинаково, иначе комиссия читает три
# разных заключения по одному хозяйству.
CATEGORY_TITLES = {
    "urgent": "Критическое устойчивое ухудшение",
    "support": "Умеренная подтверждённая аномалия",
    "clarify": "Отклонение не подтверждается",
    "monitor": "Стабильное состояние",
    "undetermined": "Недостаточно данных",
}

CATEGORY_ACTIONS = {
    "urgent": "Срочная проверка",
    "support": "Рассмотреть поддержку",
    "clarify": "Запросить сведения",
    "monitor": "Плановое наблюдение",
    "undetermined": "Уточнить данные",
}

TRUST_TITLES = {"high": "Высокое", "medium": "Среднее", "low": "Низкое"}


class FarmTrust(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(slots=True)
class FieldInput:
    """Всё, что индекс хозяйства знает о поле.

    Отдельный тип, а не модель `Field`: расчёт обязан проверяться без базы,
    и набор входных величин должен быть виден целиком в одном месте.
    """

    area_ha: float | None
    status: FieldStatus
    risk_score: float | None
    # Уверенность в оценке поля — из `risk_breakdown["confidence"]`.
    confidence: float | None = None
    # Вклады факторов — из `risk_breakdown["weights"]`. Нужны только для того,
    # чтобы назвать причину словами.
    risk_factors: dict[str, float] = dataclass_field(default_factory=dict)
    anomalies_total: int = 0
    anomalies_confirmed: int = 0
    anomalies_disputed: int = 0
    worst_anomaly_days: int | None = None
    worst_anomaly_critical: bool = False
    forecast_declining: bool = False


@dataclass(slots=True)
class FarmAssessment:
    """Итог по хозяйству. Балл и достоверность — всегда рядом."""

    support_need_score: float | None
    trust: FarmTrust
    category: ReviewCategory

    fields_total: int
    critical: int
    attention: int
    normal: int
    insufficient_data: int
    pending: int

    total_area_ha: float
    assessed_area_ha: float
    unassessed_area_ha: float
    problem_area_ha: float
    critical_area_ha: float

    assessed_share: float
    problem_share: float
    critical_share: float

    weighted_risk: float | None = None
    max_field_risk: float | None = None
    mean_confidence: float | None = None

    anomalies_total: int = 0
    anomalies_confirmed: int = 0

    # Короткая причина для строки реестра и оговорки к заключению.
    reason: str | None = None
    notes: list[str] = dataclass_field(default_factory=list)


def assess(fields: list[FieldInput]) -> FarmAssessment:
    """Свести поля хозяйства в индекс потребности в поддержке."""
    if not fields:
        return _empty()

    assessed = [f for f in fields if f.status in ASSESSED_STATUSES and f.risk_score is not None]
    problem = [f for f in assessed if f.status in PROBLEM_STATUSES]
    critical = [f for f in assessed if f.status == FieldStatus.CRITICAL]

    total_area = _area(fields)
    assessed_area = _area(assessed)
    problem_area = _area(problem)
    critical_area = _area(critical)

    notes: list[str] = []

    # Площадь известна не у всякого поля: колонка nullable, и участок мог быть
    # заведён до её расчёта. Достаточно одного такого поля, чтобы взвешивание
    # по площади начало врать — поле с неизвестной площадью весит ноль и молча
    # исчезает из оценки. Поэтому проверяем все поля хозяйства, а не только
    # оценённые: неизмеренный участок без данных обязан понижать достоверность,
    # а не растворяться в знаменателе.
    by_area = bool(fields) and all(f.area_ha and f.area_ha > 0 for f in fields)
    if not by_area:
        notes.append(
            "площадь известна не у всех полей — риск и доли посчитаны "
            "по числу полей, а не по площади"
        )

    if by_area:
        assessed_share = (assessed_area / total_area) if total_area > 0 else 0.0
        problem_share = (problem_area / assessed_area) if assessed_area > 0 else 0.0
        critical_share = (critical_area / assessed_area) if assessed_area > 0 else 0.0
    else:
        assessed_share = len(assessed) / len(fields)
        problem_share = (len(problem) / len(assessed)) if assessed else 0.0
        critical_share = (len(critical) / len(assessed)) if assessed else 0.0

    weighted_risk = _weighted(assessed, by_area)
    max_field_risk = max((f.risk_score for f in assessed), default=None)
    mean_confidence = _weighted_confidence(assessed, by_area)

    score: float | None = None
    if weighted_risk is not None and max_field_risk is not None:
        composite = (
            weighted_risk
            + BONUS_CRITICAL_SHARE * critical_share
            + BONUS_PROBLEM_SHARE * problem_share
        )
        score = round(min(100.0, max(composite, SINGLE_FIELD_FLOOR * max_field_risk)), 1)

    trust = _trust(assessed_share, mean_confidence)
    conclusive = score is not None and assessed_share >= MIN_ASSESSED_SHARE
    if score is not None and not conclusive:
        notes.append(
            f"оценено {assessed_share:.0%} площади хозяйства — для заключения этого мало"
        )

    anomalies_total = sum(f.anomalies_total for f in fields)
    anomalies_confirmed = sum(f.anomalies_confirmed for f in fields)
    anomalies_disputed = sum(f.anomalies_disputed for f in fields)
    # «Не подтверждается» — это когда радар или погода противоречат событию,
    # а не когда их нечем сверить. Неподтверждённое событие остаётся событием.
    contested = anomalies_confirmed == 0 and anomalies_disputed > 0

    category = _categorize(score, conclusive, contested)
    if contested and conclusive:
        notes.append("ни одно отклонение не подтверждено сопутствующими данными")

    return FarmAssessment(
        support_need_score=score,
        trust=trust,
        category=category,
        fields_total=len(fields),
        critical=_count(fields, FieldStatus.CRITICAL),
        attention=_count(fields, FieldStatus.ATTENTION),
        normal=_count(fields, FieldStatus.NORMAL),
        insufficient_data=_count(fields, FieldStatus.INSUFFICIENT_DATA),
        pending=_count(fields, FieldStatus.PENDING) + _count(fields, FieldStatus.FAILED),
        total_area_ha=round(total_area, 1),
        assessed_area_ha=round(assessed_area, 1),
        unassessed_area_ha=round(max(total_area - assessed_area, 0.0), 1),
        problem_area_ha=round(problem_area, 1),
        critical_area_ha=round(critical_area, 1),
        assessed_share=round(assessed_share, 3),
        problem_share=round(problem_share, 3),
        critical_share=round(critical_share, 3),
        weighted_risk=None if weighted_risk is None else round(weighted_risk, 1),
        max_field_risk=max_field_risk,
        mean_confidence=None if mean_confidence is None else round(mean_confidence, 3),
        anomalies_total=anomalies_total,
        anomalies_confirmed=anomalies_confirmed,
        reason=_reason(assessed),
        notes=notes,
    )


# ----------------------------------------------------------------------
# Вспомогательное
# ----------------------------------------------------------------------


def _empty() -> FarmAssessment:
    """Хозяйство без полей. Не ошибка: его заводят до того, как рисуют контуры."""
    return FarmAssessment(
        support_need_score=None,
        trust=FarmTrust.LOW,
        category=ReviewCategory.UNDETERMINED,
        fields_total=0,
        critical=0,
        attention=0,
        normal=0,
        insufficient_data=0,
        pending=0,
        total_area_ha=0.0,
        assessed_area_ha=0.0,
        unassessed_area_ha=0.0,
        problem_area_ha=0.0,
        critical_area_ha=0.0,
        assessed_share=0.0,
        problem_share=0.0,
        critical_share=0.0,
        notes=["в хозяйстве нет полей"],
    )


def _area(fields: list[FieldInput]) -> float:
    return sum(f.area_ha or 0.0 for f in fields)


def _count(fields: list[FieldInput], status: FieldStatus) -> int:
    return sum(1 for f in fields if f.status == status)


def _weighted(fields: list[FieldInput], by_area: bool) -> float | None:
    """Средний балл: по площади, если она известна у всех, иначе простой."""
    if not fields:
        return None
    if not by_area:
        return sum(f.risk_score or 0.0 for f in fields) / len(fields)
    total = sum(f.area_ha or 0.0 for f in fields)
    if total <= 0:
        return None
    return sum((f.risk_score or 0.0) * (f.area_ha or 0.0) for f in fields) / total


def _weighted_confidence(fields: list[FieldInput], by_area: bool) -> float | None:
    known = [f for f in fields if f.confidence is not None]
    if not known:
        return None
    if not by_area:
        return sum(f.confidence or 0.0 for f in known) / len(known)
    total = sum(f.area_ha or 0.0 for f in known)
    if total <= 0:
        return sum(f.confidence or 0.0 for f in known) / len(known)
    return sum((f.confidence or 0.0) * (f.area_ha or 0.0) for f in known) / total


def _trust(assessed_share: float, mean_confidence: float | None) -> FarmTrust:
    """Достоверность заключения — отдельно от балла.

    Нужна именно отдельным показателем: без неё «низкий риск по хозяйству,
    с которого нет снимков» неотличим от «низкий риск по хозяйству,
    отснятому пятнадцать раз».
    """
    confidence = mean_confidence if mean_confidence is not None else 0.0
    if assessed_share >= TRUST_HIGH_SHARE and confidence >= TRUST_HIGH_CONFIDENCE:
        return FarmTrust.HIGH
    if assessed_share >= TRUST_MEDIUM_SHARE and confidence >= TRUST_MEDIUM_CONFIDENCE:
        return FarmTrust.MEDIUM
    return FarmTrust.LOW


def _categorize(score: float | None, conclusive: bool, contested: bool) -> ReviewCategory:
    if score is None or not conclusive:
        return ReviewCategory.UNDETERMINED
    if score >= THRESHOLD_SUPPORT and contested:
        return ReviewCategory.CLARIFY
    if score >= THRESHOLD_URGENT:
        return ReviewCategory.URGENT
    if score >= THRESHOLD_SUPPORT:
        return ReviewCategory.SUPPORT
    return ReviewCategory.MONITOR


def _reason(assessed: list[FieldInput]) -> str | None:
    """Назвать причину словами — по самому проблемному полю хозяйства.

    Строка реестра должна отвечать на вопрос «почему он здесь», иначе балл
    остаётся числом без содержания. Берётся ведущий фактор оценки риска
    худшего поля: он уже посчитан, и придумывать поверх него нечего.
    """
    if not assessed:
        return None
    worst = max(assessed, key=lambda f: f.risk_score or 0.0)
    if (worst.risk_score or 0.0) < THRESHOLD_SUPPORT:
        return "устойчивых отклонений не обнаружено"

    if worst.worst_anomaly_critical and worst.worst_anomaly_days:
        return f"критическая аномалия {worst.worst_anomaly_days} дн."

    factors = worst.risk_factors or {}
    leading = max(factors, key=lambda key: factors[key]) if factors else None
    titles = {
        "anomaly_severity": "глубокое отклонение от нормы",
        "anomaly_duration": (
            f"длительное отклонение {worst.worst_anomaly_days} дн."
            if worst.worst_anomaly_days
            else "длительное отклонение от нормы"
        ),
        "recent_trend": "состояние ниже нормы сейчас",
        "moisture": "водный стресс",
        "weather": "засушливый период",
    }
    if leading and factors.get(leading, 0.0) > 0:
        reason = titles.get(leading, "отклонение ниже нормы")
    elif worst.forecast_declining:
        return "негативный прогноз"
    else:
        reason = "отклонение ниже нормы"

    # Прогноз дополняет причину, а не заменяет её: он относится к будущему,
    # а строка реестра прежде всего сообщает, что уже произошло.
    return f"{reason}, прогноз ухудшения" if worst.forecast_declining else reason


def field_input(
    field: Field, anomalies: list[Anomaly], forecast: ForecastRun | None
) -> FieldInput:
    """Перевести строку поля во вход расчёта по хозяйству.

    Отдельный шаг, а не передача модели напрямую: расчёт индекса обязан
    проверяться без базы, и всё, что он знает о поле, должно быть перечислено
    явно. Аномалии приходят отсортированными по тяжести, поэтому худшая — первая.
    """
    breakdown = field.risk_breakdown or {}
    worst = anomalies[0] if anomalies else None
    return FieldInput(
        area_ha=field.area_ha,
        status=field.status,
        risk_score=field.risk_score,
        confidence=breakdown.get("confidence"),
        risk_factors=breakdown.get("weights") or {},
        anomalies_total=len(anomalies),
        anomalies_confirmed=sum(1 for a in anomalies if a.trust == TRUST_CONFIRMED),
        anomalies_disputed=sum(1 for a in anomalies if a.trust == TRUST_DISPUTED),
        worst_anomaly_days=worst.duration_days if worst is not None else None,
        worst_anomaly_critical=(
            worst is not None and worst.severity == AnomalySeverity.CRITICAL
        ),
        forecast_declining=(forecast is not None and forecast.direction == "declining"),
    )
