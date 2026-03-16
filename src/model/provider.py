from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from litellm import acompletion, cost_per_token
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential


@dataclass(frozen=True)
class ModelError(Exception):
    provider: str
    status_code: int
    message: str

    def __str__(self) -> str:
        return f"{self.provider}({self.status_code}): {self.message}"


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

    def model_dump(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


def _extract_status_code(exc: Exception) -> int:
    for attr in ("status_code", "status", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    return 500


def _extract_provider(model: str) -> str:
    if "/" in model:
        return model.split("/", 1)[0]
    if model.startswith("gpt-") or model.startswith("o"):
        return "openai"
    return "unknown"


def _should_retry(exception: BaseException) -> bool:
    if not isinstance(exception, ModelError):
        return False
    return exception.status_code == 429 or 500 <= exception.status_code <= 599


class TokenTracker:
    @staticmethod
    def get_cost(model: str, usage: TokenUsage) -> float:
        try:
            prompt_cost, completion_cost = cost_per_token(
                model=model,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
            )
        except Exception:
            return 0.0
        return float(prompt_cost) + float(completion_cost)

    @staticmethod
    def from_completion(response: Any) -> TokenUsage:
        usage = getattr(response, "usage", None)
        if usage is None and isinstance(response, dict):
            usage = response.get("usage")

        if usage is None:
            return TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)

        if isinstance(usage, dict):
            prompt = int(usage.get("prompt_tokens", 0) or 0)
            completion = int(usage.get("completion_tokens", 0) or 0)
            total = int(usage.get("total_tokens", prompt + completion) or 0)
            return TokenUsage(
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=total,
            )

        prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion = int(getattr(usage, "completion_tokens", 0) or 0)
        total = int(getattr(usage, "total_tokens", prompt + completion) or 0)
        return TokenUsage(prompt_tokens=prompt, completion_tokens=completion, total_tokens=total)


class ModelProvider:
    def __init__(
        self,
        *,
        model_api_key: str | None = None,
        model_api_base: str | None = None,
        timeout_seconds: int = 60,
        max_retries: int = 3,
    ) -> None:
        self._model_api_key = model_api_key or None
        self._model_api_base = model_api_base or None
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries

    def has_any_key(self) -> bool:
        return bool(self._model_api_key)

    async def async_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> Any:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=0.3, min=0.3, max=4),
            retry=retry_if_exception(_should_retry),
            reraise=True,
        ):
            with attempt:
                try:
                    return await acompletion(
                        model=model,
                        messages=messages,
                        tools=tools,
                        timeout=self._timeout_seconds,
                        api_key=self._select_api_key(model),
                        api_base=self._model_api_base,
                        **kwargs,
                    )
                except Exception as exc:
                    raise ModelError(
                        provider=_extract_provider(model),
                        status_code=_extract_status_code(exc),
                        message=str(exc),
                    ) from exc
        raise ModelError(
            provider=_extract_provider(model),
            status_code=500,
            message="completion failed",
        )

    async def async_stream_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        try:
            stream = await acompletion(
                model=model,
                messages=messages,
                tools=tools,
                timeout=self._timeout_seconds,
                api_key=self._select_api_key(model),
                api_base=self._model_api_base,
                stream=True,
                **kwargs,
            )
            async for chunk in stream:
                yield chunk
        except Exception as exc:
            raise ModelError(
                provider=_extract_provider(model),
                status_code=_extract_status_code(exc),
                message=str(exc),
            ) from exc

    def _select_api_key(self, model: str) -> str | None:
        _ = model
        return self._model_api_key
