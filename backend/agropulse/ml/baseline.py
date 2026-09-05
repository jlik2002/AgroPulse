"""ВРЕМЕННАЯ ЗАГЛУШКА вместо сервиса ML-моделей. ПОДЛЕЖИТ УДАЛЕНИЮ.

Модуль существует ровно для одного: дать разработке остальной части сервиса
идти, пока сервис моделей не готов. Восстановление пропусков здесь —
приближение по соседним точкам, прогноз — возврат к климатической норме.

Это не резервный механизм и не запасной вариант. Когда сервис моделей будет
подключён, модуль удаляется вместе с настройкой `ml_use_dev_stub` и веткой
в `ml/resolve.py`. Отсутствие сервиса моделей в готовом решении должно быть
ошибкой, а не поводом подставить приближение.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import numpy as np
from scipy.signal import savgol_filter

from agropulse.ml.client import (
    ForecastPoint,
    ForecastRequest,
    ForecastResult,
    ImputeRequest,
    ImputeResult,
    Prediction,
)

logger = logging.getLogger(__name__)

# --- восстановление пропусков ---

# Полуширина окна сглаживания в сутках. Порядка длины типичного интервала
# между пригодными снимками Sentinel-2.
SMOOTH_WINDOW_DAYS = 11
POLYNOMIAL_ORDER = 2

# Максимальная длина пропуска, который считаем восстановимым. За горизонтом
# в месяц интерполяция перестаёт нести информацию о состоянии поля.
MAX_GAP_DAYS = 30

MIN_OBSERVATIONS = 4

# --- прогноз ---

# Сколько последних суток берём для оценки текущего отклонения от нормы.
DEVIATION_WINDOW_DAYS = 21

# За сколько суток отклонение затухает до нормы. Смысл: заглушка не умеет
# предсказывать развитие стресса, она лишь предполагает, что поле постепенно
# возвращается к своей типичной динамике. Чем дальше горизонт, тем ближе
# прогноз к норме и тем шире интервал.
DEVIATION_DECAY_DAYS = 21.0

MIN_OBSERVATIONS_FOR_FORECAST = 5

# Свежесть последнего наблюдения. По ряду месячной давности прогнозировать
# нечего: за это время поле могло измениться как угодно.
MAX_STALENESS_DAYS = 21


class BaselineMLClient:
    """Заглушка MLClient на период разработки. Подлежит удалению."""

    name = "dev_stub"

    def is_available(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # Восстановление пропусков
    # ------------------------------------------------------------------

    def impute(self, request: ImputeRequest) -> ImputeResult:
        """Восстановить пропуски интерполяцией со сглаживанием.

        Линейная интерполяция на суточную сетку, затем фильтр Савицкого — Голея.
        Скользящее среднее здесь хуже: оно срезает пики и впадины, а именно они
        и являются предметом поиска. Фильтр Савицкого — Голея подгоняет полином
        и сохраняет форму экстремумов.

        Экстраполяция за пределы наблюдений сознательно не выполняется:
        восстановленное значение обязано опираться на наблюдения с обеих сторон.
        """
        known = sorted(
            (point.date, point.primary_ndvi)
            for point in request.observations
            if point.primary_ndvi is not None
        )
        if len(known) < MIN_OBSERVATIONS:
            logger.info(
                "Поле %s: наблюдений %s, для восстановления нужно минимум %s",
                request.polygon_id, len(known), MIN_OBSERVATIONS,
            )
            return ImputeResult(predictions=[], model_version=self.name, source=self.name)

        first, last = known[0][0], known[-1][0]
        grid = [first + timedelta(days=offset) for offset in range((last - first).days + 1)]

        known_offsets = np.array([(day - first).days for day, _ in known], dtype=float)
        known_values = np.array([value for _, value in known], dtype=float)
        grid_offsets = np.arange(len(grid), dtype=float)

        interpolated = np.interp(grid_offsets, known_offsets, known_values)

        # Окно фильтра должно быть нечётным и не длиннее ряда.
        window = min(SMOOTH_WINDOW_DAYS, len(grid) if len(grid) % 2 else len(grid) - 1)
        if window >= POLYNOMIAL_ORDER + 2:
            window = window if window % 2 else window - 1
            smoothed = savgol_filter(interpolated, window_length=window, polyorder=POLYNOMIAL_ORDER)
        else:
            smoothed = interpolated

        by_offset = {
            int(offset): float(value)
            for offset, value in zip(grid_offsets, smoothed, strict=True)
        }

        predictions: list[Prediction] = []
        for target in request.targets:
            if not (first <= target <= last):
                # За пределами наблюдений это была бы экстраполяция.
                continue
            gap = _distance_to_nearest_observation(target, known)
            if gap > MAX_GAP_DAYS:
                continue

            value = by_offset.get((target - first).days)
            if value is None:
                continue

            predictions.append(
                Prediction(
                    date=target,
                    value=round(float(np.clip(value, -1.0, 1.0)), 6),
                    # Уверенность падает с удалением от ближайшего наблюдения.
                    confidence=round(max(0.1, 1.0 - gap / MAX_GAP_DAYS), 3),
                )
            )

        return ImputeResult(predictions=predictions, model_version=self.name, source=self.name)

    # ------------------------------------------------------------------
    # Прогноз
    # ------------------------------------------------------------------

    def forecast(self, request: ForecastRequest) -> ForecastResult:
        """Прогноз NDVI как возврат к норме от текущего отклонения.

        Метод сознательно простой: заглушка не моделирует развитие стресса,
        она переносит текущее отклонение от нормы вперёд с затуханием.

        Без климатической нормы прогноз не строится вовсе. Экстраполяция тренда
        в отрыве от сезонной кривой предсказывала бы рост посреди уборки урожая.
        """
        known = sorted(
            (point.date, point.primary_ndvi)
            for point in request.observations
            if point.primary_ndvi is not None
        )
        if len(known) < MIN_OBSERVATIONS_FOR_FORECAST:
            return self._no_forecast(
                f"наблюдений {len(known)}, для прогноза нужно минимум "
                f"{MIN_OBSERVATIONS_FOR_FORECAST}"
            )
        if not request.climatology:
            return self._no_forecast("нет климатической нормы поля на даты прогноза")

        last_date = known[-1][0]
        start = last_date + timedelta(days=1)
        horizon = [start + timedelta(days=offset) for offset in range(request.horizon_days)]

        staleness = (horizon[0] - last_date).days
        if staleness > MAX_STALENESS_DAYS:
            return self._no_forecast(
                f"последнее наблюдение старше {MAX_STALENESS_DAYS} суток"
            )

        # Текущее отклонение от нормы по последним неделям.
        recent = [
            (day, value) for day, value in known
            if (last_date - day).days <= DEVIATION_WINDOW_DAYS
        ]
        deviations = [
            value - request.climatology[day][0]
            for day, value in recent
            if day in request.climatology
        ]
        deviation = float(np.mean(deviations)) if deviations else 0.0

        points: list[ForecastPoint] = []
        for step, day in enumerate(horizon, start=1):
            norm = request.climatology.get(day)
            if norm is None:
                continue
            mean, std = norm
            # Затухание отклонения к норме.
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
            return self._no_forecast("норма не покрывает даты прогноза")

        change = points[-1].value - points[0].value
        if change < -0.03:
            direction = "declining"
        elif change > 0.03:
            direction = "improving"
        else:
            direction = "stable"

        # Уровень риска определяется величиной текущего отставания от нормы,
        # а не направлением: поле, стабильно сидящее ниже нормы, тревожнее
        # поля, которое снижается штатно вместе с сезоном.
        if deviation < -0.10:
            risk_level = "high"
        elif deviation < -0.05:
            risk_level = "moderate"
        else:
            risk_level = "low"

        return ForecastResult(
            points=points,
            model_version=self.name,
            source=self.name,
            direction=direction,
            risk_level=risk_level,
            # Уверенность падает с устареванием последнего наблюдения.
            confidence=round(max(0.1, 1.0 - staleness / (MAX_STALENESS_DAYS + 1)), 3),
            # Ровно те величины, на которых построен прогноз. Отдаём их наружу,
            # чтобы интерфейс объяснял прогноз его собственными причинами,
            # а не разложением риска текущего состояния.
            factors={
                "deviation_from_norm": round(deviation, 4),
                "staleness_days": staleness,
                "change_over_horizon": round(change, 4),
                "observations_used": len(known),
                "horizon_days": len(points),
            },
        )

    def _no_forecast(self, reason: str) -> ForecastResult:
        """Отказ от прогноза с указанием причины.

        Отсутствие прогноза честнее выдуманного, поэтому причина обязательна
        и показывается пользователю.
        """
        return ForecastResult(
            points=[], model_version=self.name, source=self.name, insufficient_reason=reason
        )


def _distance_to_nearest_observation(target: date, known: list[tuple[date, float]]) -> int:
    return min(abs((target - day).days) for day, _ in known)
