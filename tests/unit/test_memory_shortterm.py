import json

import pytest

from src.memory.shortterm import ShortTermMemory


class FakeRedis:
    def __init__(self) -> None:
        self._strings: dict[str, str] = {}
        self._lists: dict[str, list[str]] = {}
        self._expirations: dict[str, int] = {}

    async def rpush(self, key: str, value: str) -> int:
        data = self._lists.setdefault(key, [])
        data.append(value)
        return len(data)

    async def lrange(self, key: str, start: int, stop: int) -> list[str]:
        data = self._lists.get(key, [])
        length = len(data)
        if length == 0:
            return []
        if start < 0:
            start = max(0, length + start)
        if stop < 0:
            stop = length + stop
        stop = min(length - 1, stop)
        if start > stop:
            return []
        return data[start : stop + 1]

    async def llen(self, key: str) -> int:
        return len(self._lists.get(key, []))

    async def ltrim(self, key: str, start: int, stop: int) -> bool:
        data = self._lists.get(key, [])
        length = len(data)
        if length == 0:
            return True
        if start < 0:
            start = max(0, length + start)
        if stop < 0:
            stop = length + stop
        stop = min(length - 1, stop)
        self._lists[key] = data[start : stop + 1] if start <= stop else []
        return True

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self._strings[key] = value
        if ex is not None:
            self._expirations[key] = ex
        return True

    async def get(self, key: str) -> str | None:
        return self._strings.get(key)

    async def expire(self, key: str, seconds: int) -> bool:
        self._expirations[key] = seconds
        return True

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if key in self._strings:
                del self._strings[key]
                deleted += 1
            if key in self._lists:
                del self._lists[key]
                deleted += 1
            self._expirations.pop(key, None)
        return deleted


@pytest.mark.asyncio
async def test_shortterm_crud_and_ttl() -> None:
    redis = FakeRedis()
    memory = ShortTermMemory(redis_client=redis)  # type: ignore[arg-type]

    await memory.append_message("s1", {"type": "human", "content": "hi"})
    await memory.append_message("s1", {"type": "ai", "content": "hello"})

    messages = await memory.get_messages("s1", limit=10)
    assert messages == [
        {"type": "human", "content": "hi"},
        {"type": "ai", "content": "hello"},
    ]
    assert redis._expirations[memory.messages_key("s1")] == 86_400

    await memory.clear_session("s1")
    assert await memory.get_messages("s1", limit=10) == []


@pytest.mark.asyncio
async def test_shortterm_compresses_when_threshold_reached() -> None:
    redis = FakeRedis()
    memory = ShortTermMemory(
        redis_client=redis,  # type: ignore[arg-type]
        compress_threshold=5,
        keep_recent_count=2,
    )
    for index in range(6):
        await memory.append_message("s2", {"type": "human", "content": f"msg-{index}"})

    remaining = await memory.get_messages("s2", limit=10)
    assert [item["content"] for item in remaining] == ["msg-4", "msg-5"]

    summary = await redis.get(memory.summary_key("s2"))
    assert summary is not None
    assert "msg-0" in summary


@pytest.mark.asyncio
async def test_shortterm_budget_uses_summary_when_possible() -> None:
    redis = FakeRedis()
    memory = ShortTermMemory(redis_client=redis, compress_threshold=3, keep_recent_count=2)  # type: ignore[arg-type]

    await memory.append_message("s3", {"type": "human", "content": "one"})
    await memory.append_message("s3", {"type": "human", "content": "two"})
    await memory.append_message("s3", {"type": "human", "content": "three"})
    await memory.append_message("s3", {"type": "human", "content": "four"})

    context = await memory.get_context_within_budget("s3", max_tokens=50)
    assert len(context) >= 2
    assert context[0]["type"] == "system"
    assert "Summary" in context[0]["content"]

    raw_messages = [json.loads(item) for item in redis._lists[memory.messages_key("s3")]]
    assert len(raw_messages) == 2
