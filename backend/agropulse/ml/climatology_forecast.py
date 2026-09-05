"""Прогноз NDVI как возврат к климатической норме поля.

Модель V6 решает задачу восстановления пропусков: она вычисляет точку между
наблюдениями и требует соседей с обеих сторон. Прогнозировать вперёд она
не умеет и не задумывалась для этого, поэтому прогноз считается отдельно.

Метод сознательно простой: текущее отклонение от нормы переносится вперёд
с затуханием. Развитие стресса он не моделирует. Экстраполяция тренда
в отрыве от сезонной кривой здесь не годится — она предсказывала бы рост
посреди уборки урожая, поэтому без нормы прогноз не строится вовсе.

Раньше этот расчёт лежал в `ml/baseline.py` — временной заглушке, подлежащей
удалению. Прогноз заглушкой не является и вместе с ней удалён быть не должен,
поэтому вынесен сюда.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np

from agropulse.ml.client import ForecastPoint, ForecastRequest, ForecastResult

# Сколько последних суток берём для оценки текущего отклонения от нормы.
DEVIATION_WINDOW_DAYS = 21

# За сколько суток отклонение затухает до нормы. Чем дальше горизонт, тем
# ближе прогноз к норме и тем шире интервал.
DEVIATION_DECAY_DAYS = 21.0

MIN_OBSERVATIONS = 5

# Свежесть последнего наблюдения. По ряду месячной давности прогнозировать
# нечего: за это время поле могло измениться как угодно.
MAX_STALENESS_DAYS = 21


def forecast(request: ForecastRequest, *, model_version: str, source: str) -> ForecastResult:
    """Спрогнозировать NDVI на горизонт вперёд."""
    known = sorted(
        (point.date, point.primary_ndvi)
        for point in request.observations
        if point.primary_ndvi is not None
    )
    if len(known) < MIN_OBSERVATIONS:
        return _no_forecast(
            f"наблюдений {len(known)}, для прогноза нужно минимум {MIN_OBSERVATIONS}",
            model_version, source,
        )
    if not request.climatology:
        return _no_forecast(
            "нет климатической нормы поля на даты прогноза", model_version, source
        )

    last_date = known[-1][0]
    start = last_date + timedelta(days=1)
    horizon = [start + timedelta(days=offset) for offset in range(request.horizon_days)]

    staleness = (horizon[0] - last_date).days
    if staleness > MAX_STALENESS_DAYS:
        return _no_forecast(
            f"последнее наблюдение старше {MAX_STALENESS_DAYS} суток", model_version, source
        )

    # Текущее отклонение от нормы по последним неделям.
    recent = [
        (day, value) for day, value in known if (last_date - day).days <= DEVIATION_WINDOW_DAYS
    ]
    deviations = [
        value - request.climatology[day][0] for day, value in recent if day in request.climatology
    ]
    deviation = float(np.mean(deviations)) if deviations else 0.0

    points: list[ForecastPoint] = []
    for step, day in enumerate(horizon, start=1):
        norm = request.climatology.get(day)
        if norm is None:
            continue
        mean, std = norm
        damped = deviation * float(np.exp(-step / DEVIATION_DECAY_DAYS))
        value = float(np.clip(mean + damped, -1.0, 1.0))
        # Интервал расширяется с горизонтом: дальше — менее уверенно.
        spread = std * (1.0 + step / request.horizon_days)
        points.append(
            ForecastPoint(
                date=day,
                value=round(value, 6),
                low=round(float(np.clip(value - spread, -1.0, 1.0)), 6),
                high=round(float(np.clip(value + spread, -1.0, 1.0)), 6),
            )
        )

    if not points:
        return _no_forecast("норма не покрывает даты прогноза", model_version, source)

    change = points[-1].value - points[0].value
    if change < -0.03:
        direction = "declining"
    elif change > 0.03:
        direction = "improving"
    else:
        direction = "stable"

    # Уровень риска определяется величиной текущего отставания от нормы,
    # а не направлением: поле, стабильно сидящее ниже нормы, тревожнее поля,
    # которое снижается штатно вместе с сезоном.
    if deviation < -0.10:
        risk_level = "high"
    elif deviation < -0.05:
        risk_level = "moderate"
    else:
        risk_level = "low"

    return ForecastResult(
        points=points,
        model_version=model_version,
        source=source,
        direction=direction,
        risk_level=risk_level,
        # Уверенность падает с устареванием последнего наблюдения.
        confidence=round(max(0.1, 1.0 - staleness / (MAX_STALENESS_DAYS + 1)), 3),
        # Ровно те величины, на которых построен прогноз. Интерфейс объясняет
        # прогноз его собственными причинами, а не разложением текущего риска.
        factors={
            "deviation_from_norm": round(deviation, 4),
            "staleness_days": staleness,
            "change_over_horizon": round(change, 4),
            "observations_used": len(known),
            "horizon_days": len(points),
        },
    )


def _no_forecast(reason: str, model_version: str, source: str) -> ForecastResult:
    """Отказ от прогноза с указанием причины.

    Отсутствие прогноза честнее выдуманного, поэтому причина обязательна
    и показывается пользователю.
    """
    return ForecastResult(
        points=[], model_version=model_version, source=source, insufficient_reason=reason
    )
