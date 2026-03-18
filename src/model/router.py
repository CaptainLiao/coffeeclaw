from __future__ import annotations

from typing import Any

import structlog

from src.model.provider import ModelError, ModelProvider

logger = structlog.get_logger(__name__)

FALLBACK_STATUS_CODES = {500, 502, 503, 504}


class BasicRouter:
    def __init__(self, *, provider: ModelProvider, primary: str, fallback: str) -> None:
        self._provider = provider
        self._primary = primary
        self._fallback = fallback

    async def call(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> Any:
        try:
            return await self._provider.async_completion(
                messages=messages,
                model=self._primary,
                tools=tools,
                **kwargs,
            )
        except ModelError as exc:
            if exc.status_code not in FALLBACK_STATUS_CODES or self._fallback == self._primary:
                raise
            logger.warning(
                "Primary model failed, fallback enabled",
                primary=self._primary,
                fallback=self._fallback,
                status_code=exc.status_code,
                message=exc.message,
            )
            try:
                return await self._provider.async_completion(
                    messages=messages,
                    model=self._fallback,
                    tools=tools,
                    **kwargs,
                )
            except ModelError as fallback_exc:
                logger.error(
                    "Fallback model also failed",
                    primary=self._primary,
                    fallback=self._fallback,
                    primary_status_code=exc.status_code,
                    fallback_status_code=fallback_exc.status_code,
                )
                raise self._compose_fallback_error(
                    primary_error=exc,
                    fallback_error=fallback_exc,
                ) from fallback_exc

    def _compose_fallback_error(
        self,
        *,
        primary_error: ModelError,
        fallback_error: ModelError,
    ) -> ModelError:
        return ModelError(
            provider=fallback_error.provider,
            status_code=fallback_error.status_code,
            message=(
                f"Primary model {self._primary} failed with "
                f"{primary_error.provider}({primary_error.status_code}): {primary_error.message}; "
                f"fallback model {self._fallback} failed with "
                f"{fallback_error.provider}({fallback_error.status_code}): {fallback_error.message}"
            ),
        )
