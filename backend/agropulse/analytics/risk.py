"""Составной риск и приоритет выезда.

Итоговый балл нужен не сам по себе, а чтобы упорядочить поля: куда ехать
первым. Поэтому он объяснимый — вместе с баллом всегда возвращается вклад
каждого фактора, и пользователь видит, из чего сложилась оценка.

Веса подобраны исходя из практического смысла, а не оптимизацией: сила и
длительность отклонения важнее сопутствующих признаков, а качество данных
не добавляет риска, но снижает доверие к выводу.

Отдельное правило: полю с недостаточными данными риск не выставляется вовсе.
Выдуманный балл хуже честного «данных не хватает» — он выглядит как знание.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date

from agropulse.analytics.anomalies import AnomalyPeriod
from agropulse.db.models import FieldStatus

logger = logging.getLogger(__name__)

# Вклады факторов в итоговый балл 0..100.
WEIGHTS = {
    "anomaly_severity": 30.0,   # насколько глубоко просел индекс
    "anomaly_duration": 20.0,   # как долго держится отклонение
    "recent_trend": 20.0,       # куда движется поле прямо сейчас
    "moisture": 15.0,           # динамика индекса влажности
    "weather": 15.0,            # засушливость и жара в период отклонения
}

# Границы статусов по итоговому баллу.
THRESHOLD_CRITICAL = 60.0
THRESHOLD_ATTENTION = 30.0

# Ниже этого числа пригодных наблюдений вывод считается необеспеченным.
MIN_OBSERVATIONS_FOR_RISK = 5


@dataclass(slots=True)
class RiskAssessment:
    score: float | None
    status: FieldStatus
    breakdown: dict[str, float] = dataclass_field(default_factory=dict)
    explanation: list[str] = dataclass_field(default_factory=list)
    confidence: float = 0.0
    insufficient_reason: str | None = None


def assess(
    anomalies: list[AnomalyPeriod],
    recent_zscores: list[tuple[date, float]],
    observed_count: int,
    mean_valid_fraction: float | None,
    restored_fraction: float,
    climatology_available: bool,
) -> RiskAssessment:
    """Оценить риск по полю."""
    if observed_count < MIN_OBSERVATIONS_FOR_RISK:
        return RiskAssessment(
            score=None,
            status=FieldStatus.INSUFFICIENT_DATA,
            insufficient_reason=(
                f"пригодных наблюдений {observed_count}, "
                f"нужно минимум {MIN_OBSERVATIONS_FOR_RISK}"
            ),
        )
    if not climatology_available:
        return RiskAssessment(
            score=None,
            status=FieldStatus.INSUFFICIENT_DATA,
            insufficient_reason="недостаточно собственной истории поля для построения нормы",
        )

    breakdown: dict[str, float] = {}
    explanation: list[str] = []

    worst = min(anomalies, key=lambda a: a.max_zscore) if anomalies else None

    # --- сила отклонения ---
    if worst is not None:
        # z = -3 и глубже считаем предельным случаем.
        severity = min(abs(worst.max_zscore) / 3.0, 1.0)
        breakdown["anomaly_severity"] = round(severity * WEIGHTS["anomaly_severity"], 2)
        explanation.append(
            f"максимальное отклонение от нормы z={worst.max_zscore:.2f} "
            f"({worst.start_date}—{worst.end_date})"
        )
    else:
        breakdown["anomaly_severity"] = 0.0

    # --- длительность ---
    if worst is not None:
        # Месяц устойчивого угнетения считаем предельным случаем.
        duration = min(worst.duration_days / 30.0, 1.0)
        breakdown["anomaly_duration"] = round(duration * WEIGHTS["anomaly_duration"], 2)
        explanation.append(f"длительность аномалии {worst.duration_days} дн.")
    else:
        breakdown["anomaly_duration"] = 0.0

    # --- текущее состояние относительно нормы ---
    # Считается по z-score, а не по абсолютному изменению NDVI. Абсолютная
    # разность здесь непригодна: в конце сезона индекс снижается у любого
    # здорового поля из-за созревания, и оценка по сырой динамике выдавала бы
    # максимальный риск каждому полю, проанализированному осенью.
    recent_z = _recent_deviation(recent_zscores)
    if recent_z is not None:
        # z = -2 в текущей фазе считаем предельным случаем.
        deviation = min(max(-recent_z / 2.0, 0.0), 1.0)
        breakdown["recent_trend"] = round(deviation * WEIGHTS["recent_trend"], 2)
        if recent_z < -0.5:
            explanation.append(
                f"состояние ниже нормы прямо сейчас: z={recent_z:.2f} по последним наблюдениям"
            )
        elif recent_z > 0.5:
            explanation.append(f"состояние выше нормы: z={recent_z:+.2f}")
    else:
        breakdown["recent_trend"] = 0.0

    # --- влажность и погода ---
    factors = worst.factors if worst is not None else {}

    ndmi_trend = factors.get("ndmi_trend")
    if ndmi_trend is not None:
        drying = min(max(-ndmi_trend / 0.10, 0.0), 1.0)
        breakdown["moisture"] = round(drying * WEIGHTS["moisture"], 2)
        if ndmi_trend < -0.03:
            explanation.append(f"индекс влажности падает: {ndmi_trend:+.3f}")
    else:
        breakdown["moisture"] = 0.0

    weather_score = 0.0
    precipitation = factors.get("precipitation_sum")
    temperature_max = factors.get("temperature_max")
    if precipitation is not None and precipitation < 10.0:
        weather_score += 0.5
        explanation.append(f"осадков за период аномалии {precipitation:.1f} мм")
    if temperature_max is not None and temperature_max > 32.0:
        weather_score += 0.5
        explanation.append(f"максимальная температура {temperature_max:.1f} °C")
    breakdown["weather"] = round(min(weather_score, 1.0) * WEIGHTS["weather"], 2)

    score = round(sum(breakdown.values()), 2)

    # Если сезон не совпал по фазе с историей поля, найденные отклонения
    # скорее означают смену культуры, чем угнетение. Балл снижается вдвое,
    # а причина проговаривается пользователю: молча занижать риск нельзя.
    phase_mismatch = any(a.phase_mismatch for a in anomalies)
    if phase_mismatch:
        score = round(score * 0.5, 2)
        explanation.append(
            "динамика сезона не совпадает с историей поля — вероятна смена культуры "
            "в севообороте; оценка снижена, требуется подтверждение культуры"
        )

    # --- доверие к выводу ---
    # Качество данных влияет не на риск, а на уверенность в нём: разрежённый
    # ряд не делает поле здоровым, он делает вывод менее надёжным.
    coverage = min(observed_count / 15.0, 1.0)
    validity = mean_valid_fraction if mean_valid_fraction is not None else 0.5
    confidence = round(
        max(0.05, 0.5 * coverage + 0.3 * validity + 0.2 * (1.0 - restored_fraction)), 3
    )
    if phase_mismatch:
        confidence = round(confidence * 0.5, 3)

    if score >= THRESHOLD_CRITICAL:
        status = FieldStatus.CRITICAL
    elif score >= THRESHOLD_ATTENTION:
        status = FieldStatus.ATTENTION
    else:
        status = FieldStatus.NORMAL
        if not explanation:
            explanation.append("устойчивых отклонений от собственной нормы поля не обнаружено")

    return RiskAssessment(
        score=score,
        status=status,
        breakdown=breakdown,
        explanation=explanation,
        confidence=confidence,
    )


def _recent_deviation(zscores: list[tuple[date, float]], window_days: int = 21) -> float | None:
    """Среднее отклонение от нормы за последние недели.

    Окно берётся от последнего наблюдения назад: интерес представляет то,
    в каком состоянии поле находится сейчас, а не в начале периода.
    """
    if not zscores:
        return None
    ordered = sorted(zscores)
    last_date = ordered[-1][0]
    window = [z for day, z in ordered if (last_date - day).days <= window_days]
    if not window:
        return None
    return round(sum(window) / len(window), 4)
