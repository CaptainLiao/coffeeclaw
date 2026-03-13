from __future__ import annotations

import json
from typing import Any

from redis.asyncio.client import Redis


def _estimate_tokens(text: str) -> int:
    # Approximate token count for mixed CN/EN content.
    return max(1, (len(text) + 3) // 4)


class ShortTermMemory:
    def __init__(
        self,
        redis_client: Redis,
        *,
        default_ttl_seconds: int = 86_400,
        compress_threshold: int = 100,
        keep_recent_count: int = 50,
    ) -> None:
        self._redis: Any = redis_client
        self._default_ttl_seconds = default_ttl_seconds
        self._compress_threshold = compress_threshold
        self._keep_recent_count = keep_recent_count

    @staticmethod
    def messages_key(session_id: str) -> str:
        return f"session:{session_id}:messages"

    @staticmethod
    def summary_key(session_id: str) -> str:
        return f"session:{session_id}:summary"

    async def append_message(self, session_id: str, message: dict[str, Any]) -> None:
        key = self.messages_key(session_id)
        await self._redis.rpush(key, json.dumps(message, ensure_ascii=False))
        await self.set_session_ttl(session_id, self._default_ttl_seconds)
        await self.compress_if_needed(session_id)

    async def get_messages(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        key = self.messages_key(session_id)
        raw = await self._redis.lrange(key, -limit, -1)
        return [json.loads(item) for item in raw]

    async def set_session_ttl(self, session_id: str, ttl_seconds: int = 86_400) -> None:
        await self._redis.expire(self.messages_key(session_id), ttl_seconds)
        await self._redis.expire(self.summary_key(session_id), ttl_seconds)

    async def clear_session(self, session_id: str) -> None:
        await self._redis.delete(self.messages_key(session_id), self.summary_key(session_id))

    async def compress_if_needed(self, session_id: str) -> None:
        messages_key = self.messages_key(session_id)
        total = await self._redis.llen(messages_key)
        if total <= self._compress_threshold:
            return

        old_count = max(0, total - self._keep_recent_count)
        if old_count == 0:
            return

        old_raw = await self._redis.lrange(messages_key, 0, old_count - 1)
        old_messages = [json.loads(item) for item in old_raw]
        summary = self._build_summary(old_messages)
        await self._redis.set(self.summary_key(session_id), summary, ex=self._default_ttl_seconds)
        await self._redis.ltrim(messages_key, -self._keep_recent_count, -1)

    async def get_context_within_budget(
        self,
        session_id: str,
        max_tokens: int,
    ) -> list[dict[str, Any]]:
        summary = await self._redis.get(self.summary_key(session_id))
        messages = await self.get_messages(session_id, limit=self._keep_recent_count)

        selected: list[dict[str, Any]] = []
        used_tokens = 0
        for message in reversed(messages):
            content = str(message.get("content", ""))
            token_cost = _estimate_tokens(content)
            if used_tokens + token_cost > max_tokens:
                break
            selected.append(message)
            used_tokens += token_cost

        selected.reverse()
        if summary:
            summary_tokens = _estimate_tokens(summary)
            if used_tokens + summary_tokens <= max_tokens:
                selected.insert(0, {"type": "system", "content": f"Summary: {summary}"})
        return selected

    @staticmethod
    def _build_summary(messages: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for message in messages[-20:]:
            role = str(message.get("type", "unknown"))
            content = str(message.get("content", "")).strip().replace("\n", " ")
            if not content:
                continue
            lines.append(f"[{role}] {content[:120]}")
        if not lines:
            return "No prior context."
        return " | ".join(lines)
