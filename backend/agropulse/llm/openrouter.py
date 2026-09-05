"""Клиент LLM через OpenRouter.

Роль модели в продукте узкая и жёстко ограниченная: она превращает уже
рассчитанные и проверенные числа в связный русский текст. Она не считает
показатели, не додумывает отсутствующие значения и не ставит диагноз.

Поэтому на входе всегда структурированный JSON с готовыми числами, а на выходе
текст, который проходит автоматическую сверку (`llm/validator.py`). Если сверка
не прошла, текст перегенерируется, а при повторной неудаче не показывается
вовсе: лучше остаться без пояснения, чем показать выдуманное число.
"""

from __future__ import annotations

import logging

import httpx

from agropulse.config import get_settings

logger = logging.getLogger(__name__)

# Модель по умолчанию. Переопределяется переменной OPENROUTER_MODEL.
# Слаг сверен со списком моделей OpenRouter.
DEFAULT_MODEL = "qwen/qwen3.8-27b"

# Предел длины ответа. Без явного значения провайдер режет ответ по своему
# умолчанию, и текст обрывается на полуслове — а если обрыв приходится
# на середину числа, сверка законно бракует его целиком.
#
# Запас взят с большим избытком над нужными 4-6 предложениями намеренно:
# рассуждающие модели тратят часть бюджета на внутренние рассуждения, и при
# тесном лимите на сам ответ токенов не остаётся, а поле content приходит пустым.
DEFAULT_MAX_TOKENS = 2000


class LLMUnavailable(RuntimeError):
    """Генерация текста недоступна: нет ключа или сервис не ответил."""


class OpenRouterClient:
    name = "openrouter"

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.openrouter_api_key.get_secret_value()
        self._base_url = settings.openrouter_base_url.rstrip("/")
        self._model = settings.openrouter_model or DEFAULT_MODEL
        self._enabled = settings.llm_enabled
        self._timeout = settings.openrouter_timeout_seconds

    def is_available(self) -> bool:
        return bool(self._enabled and self._api_key)

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> str:
        """Получить текст от модели.

        Температура низкая: задача не творческая, от модели требуется точный
        пересказ переданных фактов, а не разнообразие формулировок.
        """
        if not self.is_available():
            raise LLMUnavailable("ключ OpenRouter не задан или генерация отключена")

        payload = {
            "model": self._model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        try:
            response = httpx.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            raise LLMUnavailable(
                f"OpenRouter вернул {exc.response.status_code}: {exc.response.text[:200]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"OpenRouter недоступен: {exc}") from exc

        try:
            choice = data["choices"][0]
        except (KeyError, IndexError) as exc:
            raise LLMUnavailable(f"неожиданный формат ответа OpenRouter: {exc}") from exc

        # Причина завершения проверяется до чтения текста. Обрыв по лимиту
        # опаснее пустого ответа: оборванное на середине число выглядит
        # достоверным, но им не является.
        finish_reason = choice.get("finish_reason")
        if finish_reason == "length":
            raise LLMUnavailable(
                f"ответ модели обрезан по лимиту в {max_tokens} токенов"
            )

        # Поле content бывает пустым (null), если модель израсходовала бюджет
        # на внутренние рассуждения и не успела выдать ответ.
        content = (choice.get("message") or {}).get("content")
        text = content.strip() if isinstance(content, str) else ""
        if not text:
            raise LLMUnavailable(
                f"модель вернула пустой ответ (причина завершения: {finish_reason})"
            )
        return text
