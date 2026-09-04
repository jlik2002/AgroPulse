"""Проверки состояния сервиса.

Две разные пробы, как того требует Kubernetes:

* `/health/live`  — процесс жив. Провал означает перезапуск пода, поэтому проба
  не должна зависеть от внешних систем: недоступная база не повод убивать под.
* `/health/ready` — сервис готов принимать трафик. Здесь как раз проверяются
  зависимости, и при их отказе под просто выводится из балансировки.
"""

import logging

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from agropulse.db.session import engine
from agropulse.storage import s3

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health/live")
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def readiness(response: Response) -> dict[str, object]:
    checks: dict[str, bool] = {}

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["postgres"] = True
    except Exception as exc:
        logger.warning("Postgres недоступен: %s", exc)
        checks["postgres"] = False

    checks["s3"] = s3.healthcheck()

    ready = all(checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if ready else "degraded", "checks": checks}
