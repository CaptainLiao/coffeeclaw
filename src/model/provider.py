from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any, cast

from openai import AsyncOpenAI
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential


@dataclass
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
    normalized = model.strip()
    return normalized or "unknown"


def _should_retry(exception: BaseException) -> bool:
    if not isinstance(exception, ModelError):
        return False
    return exception.status_code == 429 or 500 <= exception.status_code <= 599


class TokenTracker:
    @staticmethod
    def get_cost(model: str, usage: TokenUsage) -> float:
        _ = (model, usage)
        return 0.0

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
        self._client = AsyncOpenAI(
            api_key=self._model_api_key,
            base_url=self._model_api_base or None,
        )

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
        normalized_model = self._normalize_model_name(model)
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=0.3, min=0.3, max=4),
            retry=retry_if_exception(_should_retry),
            reraise=True,
        ):
            with attempt:
                try:
                    request_kwargs: dict[str, Any] = {
                        "model": normalized_model,
                        "messages": messages,
                        "timeout": self._timeout_seconds,
                    }
                    if tools is not None:
                        request_kwargs["tools"] = tools
                    request_kwargs.update(kwargs)
                    self._apply_provider_compat(
                        model=normalized_model,
                        request_kwargs=request_kwargs,
                    )
                    return await self._client.chat.completions.create(**request_kwargs)
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
        normalized_model = self._normalize_model_name(model)
        try:
            request_kwargs: dict[str, Any] = {
                "model": normalized_model,
                "messages": messages,
                "timeout": self._timeout_seconds,
                "stream": True,
            }
            if tools is not None:
                request_kwargs["tools"] = tools
            request_kwargs.update(kwargs)
            self._apply_provider_compat(model=normalized_model, request_kwargs=request_kwargs)

            stream = cast(Any, await self._client.chat.completions.create(**request_kwargs))
            async for chunk in stream:
                yield chunk
        except Exception as exc:
            raise ModelError(
                provider=_extract_provider(model),
                status_code=_extract_status_code(exc),
                message=str(exc),
            ) from exc

    def _normalize_model_name(self, model: str) -> str:
        normalized = model.strip()
        if "/" in normalized:
            return normalized.split("/", 1)[1]
        return normalized

    def _apply_provider_compat(self, *, model: str, request_kwargs: dict[str, Any]) -> None:
        # Kimi OpenAI-compatible endpoints may require reasoning_content for tool calls
        # when thinking is enabled; disable it to keep payload OpenAI-compatible.
        if "kimi" not in model.lower():
            return
        extra_body = request_kwargs.get("extra_body")
        if not isinstance(extra_body, dict):
            extra_body = {}
        thinking = extra_body.get("thinking")
        if not isinstance(thinking, dict):
            thinking = {}
        thinking.setdefault("type", "disabled")
        extra_body["thinking"] = thinking
        request_kwargs["extra_body"] = extra_body
