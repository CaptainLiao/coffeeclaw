from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

INJECTION_PATTERNS = [
    re.compile(r"ignore\s+previous\s+instructions", re.IGNORECASE),
    re.compile(r"system\s*:\s*", re.IGNORECASE),
    re.compile(r"developer\s*:\s*", re.IGNORECASE),
    re.compile(r"disregard\s+all\s+prior", re.IGNORECASE),
]
PHONE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
ID_CARD_PATTERN = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
BANK_CARD_PATTERN = re.compile(r"(?<!\d)\d{16,19}(?!\d)")
DATE_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
NUMBER_PATTERN = re.compile(r"(?<!\d)\d+(?:\.\d+)?(?!\d)")


@dataclass(frozen=True)
class SecurityError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


class InputFilter:
    def check(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sanitized: list[dict[str, Any]] = []
        for message in messages:
            copied = dict(message)
            content = str(copied.get("content", ""))
            self._raise_on_injection(content)
            copied["content"] = self._redact_sensitive(content)
            sanitized.append(copied)
        return sanitized

    def _raise_on_injection(self, content: str) -> None:
        for pattern in INJECTION_PATTERNS:
            if pattern.search(content):
                logger.warning("Prompt injection detected", content=content[:200])
                raise SecurityError("Prompt injection detected.")

    def _redact_sensitive(self, content: str) -> str:
        sanitized = ID_CARD_PATTERN.sub("[REDACTED]", content)
        sanitized = BANK_CARD_PATTERN.sub("[REDACTED]", sanitized)
        sanitized = PHONE_PATTERN.sub("[REDACTED]", sanitized)
        return sanitized


class OutputFilter:
    def __init__(self, *, moderation_api_key: str | None) -> None:
        self._moderation_api_key = moderation_api_key or None

    async def check(
        self,
        *,
        response_text: str,
        tool_results: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        is_harmful = await self._is_harmful(response_text)
        if is_harmful:
            raise SecurityError("Model output blocked by safety filter.")
        warnings = self._detect_hallucination_warnings(response_text, tool_results or [])
        return {"blocked": False, "warnings": warnings}

    async def _is_harmful(self, text: str) -> bool:
        if not text.strip():
            return False

        if self._moderation_api_key:
            logger.debug("Remote moderation disabled; using local safety rules only")

        return bool(re.search(r"\b(kill|bomb|terror|violence)\b", text, flags=re.IGNORECASE))

    def _detect_hallucination_warnings(
        self,
        response_text: str,
        tool_results: list[dict[str, Any]],
    ) -> list[str]:
        if not tool_results:
            return []

        expected_values = self._collect_reference_values(tool_results)
        if not expected_values:
            return []

        mentioned = set(NUMBER_PATTERN.findall(response_text))
        mentioned.update(DATE_PATTERN.findall(response_text))
        if not mentioned:
            return []

        mismatch = [value for value in mentioned if value not in expected_values]
        if not mismatch:
            return []
        return [f"Potential hallucination values: {', '.join(sorted(mismatch)[:5])}"]

    def _collect_reference_values(self, tool_results: list[dict[str, Any]]) -> set[str]:
        values: set[str] = set()
        for item in tool_results:
            text = str(item)
            values.update(NUMBER_PATTERN.findall(text))
            values.update(DATE_PATTERN.findall(text))
        return values
