from __future__ import annotations

from typing import Any

import structlog

from src.model.provider import ModelError, ModelProvider

logger = structlog.get_logger(__name__)

FALLBACK_STATUS_CODES = {429, 500, 502, 503, 504}


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
            return await self._provider.async_completion(
                messages=messages,
                model=self._fallback,
                tools=tools,
                **kwargs,
            )
