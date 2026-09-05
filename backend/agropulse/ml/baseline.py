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

from agropulse.ml import climatology_forecast
from agropulse.ml.client import (
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

    def impute_batch(self, requests: list[ImputeRequest]) -> list[ImputeResult]:
        """Заглушка считает каждый ряд отдельно: межполевых признаков у неё нет."""
        return [self.impute(request) for request in requests]

    # ------------------------------------------------------------------
    # Прогноз
    # ------------------------------------------------------------------

    def forecast(self, request: ForecastRequest) -> ForecastResult:
        """Прогноз климатическим методом.

        Заглушкой он никогда не был: возврат к норме — тот же расчёт, что
        используется и с настоящей моделью восстановления. Живёт он теперь
        в `ml/climatology_forecast.py` и удаления вместе с этим модулем
        не подлежит.
        """
        return climatology_forecast.forecast(
            request, model_version=self.name, source=self.name
        )


def _distance_to_nearest_observation(target: date, known: list[tuple[date, float]]) -> int:
    return min(abs((target - day).days) for day, _ in known)
