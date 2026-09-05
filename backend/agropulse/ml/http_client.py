"""REST-клиент к внешнему сервису ML-моделей.

Контракт описан в `docs/ML_API.md`. Транспорт спрятан здесь целиком, поэтому
переход на брокер сообщений затронет только этот модуль.

Клиент проверяет доступность сервиса перед обращением и сверяет состав
признаков с тем, что строит `features/contract`. Любая сетевая или протокольная
ошибка превращается в `ProviderError`, чтобы вызывающая сторона переключилась
на локальный baseline, а не уронила обработку поля.
"""

from __future__ import annotations

import logging
from datetime import date

import httpx

from agropulse.config import get_settings
from agropulse.features import contract
from agropulse.ml.client import (
    ForecastPoint,
    ForecastRequest,
    ForecastResult,
    ImputeRequest,
    ImputeResult,
    Prediction,
)
from agropulse.providers.base import ProviderError

logger = logging.getLogger(__name__)


class HttpMLClient:
    """Клиент моделей поверх HTTP."""

    name = "ml_service"

    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.ml_service_url.rstrip("/")
        self._timeout = settings.ml_service_timeout_seconds
        self._health_timeout = settings.ml_health_timeout_seconds
        self._model_version: str | None = None

    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Быстрая проверка живости сервиса.

        Таймаут намеренно короткий: при отсутствующем сервисе обработка поля
        не должна ждать полный таймаут запроса на каждом поле.
        """
        try:
            response = httpx.get(f"{self._base_url}/health", timeout=self._health_timeout)
            return response.status_code < 400
        except httpx.HTTPError:
            return False

    def model_info(self) -> dict:
        """Описание подключённой модели вместе со списком ожидаемых признаков."""
        payload = self._request("GET", "/v1/model-info")
        self._model_version = payload.get("model_version")

        expected = payload.get("expected_features") or []
        if expected:
            matches, missing, extra = contract.compare_with_expected(expected)
            payload["features_match"] = matches
            payload["features_missing"] = missing
            payload["features_extra"] = extra
        return payload

    # ------------------------------------------------------------------

    def impute(self, request: ImputeRequest) -> ImputeResult:
        body = {
            "request_id": request.polygon_id,
            "series": [
                {
                    "polygon_id": request.polygon_id,
                    "crop_type": request.crop_type,
                    "observations": [
                        {
                            "date": point.date.isoformat(),
                            "primary_ndvi": point.primary_ndvi,
                            "features": point.features,
                        }
                        for point in request.observations
                    ],
                    "targets": [day.isoformat() for day in request.targets],
                }
            ],
        }
        payload = self._request("POST", "/v1/impute", body)

        predictions = [
            Prediction(
                date=date.fromisoformat(item["date"]),
                value=float(item["primary_ndvi_pred"]),
                confidence=item.get("confidence"),
            )
            for item in payload.get("predictions", [])
            if item.get("primary_ndvi_pred") is not None
        ]
        return ImputeResult(
            predictions=predictions,
            model_version=payload.get("model_version", "unknown"),
            source=self.name,
        )

    def forecast(self, request: ForecastRequest) -> ForecastResult:
        body = {
            "request_id": request.polygon_id,
            "horizon_days": request.horizon_days,
            "series": [
                {
                    "polygon_id": request.polygon_id,
                    "crop_type": request.crop_type,
                    "sowing_date": (
                        request.sowing_date.isoformat() if request.sowing_date else None
                    ),
                    "observations": [
                        {
                            "date": point.date.isoformat(),
                            "primary_ndvi": point.primary_ndvi,
                            "features": point.features,
                        }
                        for point in request.observations
                    ],
                    "weather_forecast": [
                        {
                            "date": point.date.isoformat(),
                            "t2m_mean": point.temperature,
                            "tp_sum": point.precipitation,
                        }
                        for point in request.weather_forecast
                    ],
                }
            ],
        }
        payload = self._request("POST", "/v1/forecast", body)

        forecasts = payload.get("forecasts") or []
        if not forecasts:
            return ForecastResult(
                points=[],
                model_version=payload.get("model_version", "unknown"),
                source=self.name,
                insufficient_reason="сервис моделей не вернул прогноз",
            )

        first = forecasts[0]
        return ForecastResult(
            points=[
                ForecastPoint(
                    date=date.fromisoformat(item["date"]),
                    value=float(item["ndvi_pred"]),
                    low=item.get("ndvi_lo"),
                    high=item.get("ndvi_hi"),
                )
                for item in first.get("points", [])
                if item.get("ndvi_pred") is not None
            ],
            model_version=payload.get("model_version", "unknown"),
            source=self.name,
            direction=first.get("direction"),
            risk_level=first.get("risk_level"),
            confidence=first.get("confidence"),
            insufficient_reason=first.get("insufficient_reason"),
        )

    # ------------------------------------------------------------------

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        url = f"{self._base_url}{path}"
        try:
            response = httpx.request(method, url, json=body, timeout=self._timeout)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                f"сервис моделей вернул {exc.response.status_code} на {path}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"сервис моделей недоступен: {exc}") from exc
        except ValueError as exc:
            raise ProviderError(f"сервис моделей вернул не JSON на {path}: {exc}") from exc
