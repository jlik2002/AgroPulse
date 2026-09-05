"""Сборка пояснений: подготовка данных, генерация, сверка.

Модуль связывает три части: формирует компактный JSON из результатов расчёта,
получает текст от модели и пропускает его через сверку чисел. Наружу отдаётся
либо проверенный текст, либо ничего с указанием причины.

Повторная попытка выполняется один раз и с явным указанием на ошибку: если
модель вымышляет числа систематически, дальнейшие попытки не помогут, а время
обработки поля вырастет.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from agropulse.llm import prompts
from agropulse.llm.openrouter import LLMUnavailable, OpenRouterClient
from agropulse.llm.validator import verify

logger = logging.getLogger(__name__)

RETRY_HINT = (
    "\n\nПредыдущий ответ забракован: в нём встретились числа или даты, "
    "которых нет в переданных данных ({violations}). "
    "Перепиши текст, используя только переданные значения."
)


@dataclass(slots=True)
class Narrative:
    text: str | None
    verified: bool
    skipped_reason: str | None = None


def _generate(prompt_template: str, payload: dict, temperature: float = 0.2) -> Narrative:
    client = OpenRouterClient()
    if not client.is_available():
        return Narrative(
            text=None,
            verified=False,
            skipped_reason="генерация пояснений отключена или не задан ключ OpenRouter",
        )

    serialized = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    user_prompt = prompt_template.format(payload=serialized)

    for attempt in (1, 2):
        try:
            text = client.complete(prompts.SYSTEM_PROMPT, user_prompt, temperature)
        except LLMUnavailable as exc:
            logger.warning("Генерация не выполнена: %s", exc)
            return Narrative(text=None, verified=False, skipped_reason=str(exc))

        ok, violations = verify(text, payload)
        if ok:
            return Narrative(text=text, verified=True)

        logger.warning("Попытка %s: текст не прошёл сверку чисел", attempt)
        if attempt == 1:
            user_prompt += RETRY_HINT.format(violations="; ".join(violations[:3]))

    # Показать непроверенный текст нельзя: в отчёте руководителю выдуманное
    # число хуже отсутствия пояснения.
    return Narrative(
        text=None,
        verified=False,
        skipped_reason="сгенерированный текст не прошёл сверку чисел с исходными данными",
    )


def field_summary(payload: dict) -> Narrative:
    return _generate(prompts.FIELD_SUMMARY_PROMPT, payload)


def anomaly_explanation(payload: dict) -> Narrative:
    return _generate(prompts.ANOMALY_EXPLANATION_PROMPT, payload)


def checklist(payload: dict) -> Narrative:
    return _generate(prompts.CHECKLIST_PROMPT, payload)


def project_summary(payload: dict) -> Narrative:
    return _generate(prompts.PROJECT_SUMMARY_PROMPT, payload)
