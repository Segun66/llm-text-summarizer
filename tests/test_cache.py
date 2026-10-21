import asyncio
import hashlib
import json

import pytest

from app.llm.prompts import PROMPT_VERSION
from app.models.summarize import SummarizeRequest
from app.services.cache import MemorySummaryCache
from app.services.summarizer import SummarizationService
from app.utils.errors import (
    LLMAuthenticationError,
    LLMInvalidResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeLLM:
    def __init__(self, error=None):
        self.error = error
        self.messages = []

    async def generate(self, messages):
        self.messages.append(messages)
        if self.error:
            raise self.error
        return "Summary."


def test_cache_miss_hit_and_expiry_at_exact_deadline():
    clock = FakeClock()
    cache = MemorySummaryCache(ttl_seconds=300, clock=clock)

    async def exercise():
        assert await cache.get("missing") is None
        await cache.set("key", "summary")
        assert await cache.get("key") == "summary"
        clock.advance(299.999)
        assert await cache.get("key") == "summary"
        clock.advance(0.001)
        assert await cache.get("key") is None
        assert await cache.get("key") is None
        assert "key" not in cache._entries

    asyncio.run(exercise())


def test_hits_do_not_extend_ttl_but_overwrite_resets_it():
    clock = FakeClock()
    cache = MemorySummaryCache(ttl_seconds=10, clock=clock)

    async def exercise():
        await cache.set("key", "first")
        clock.advance(9)
        assert await cache.get("key") == "first"
        clock.advance(1)
        assert await cache.get("key") is None
        await cache.set("key", "second")
        clock.advance(9)
        await cache.set("key", "replacement")
        clock.advance(2)
        assert await cache.get("key") == "replacement"
        clock.advance(8)
        assert await cache.get("key") is None

    asyncio.run(exercise())


def test_cache_removes_expired_entries_before_lru_eviction():
    clock = FakeClock()
    cache = MemorySummaryCache(max_entries=2, ttl_seconds=10, clock=clock)

    async def exercise():
        await cache.set("old", "old")
        clock.advance(5)
        await cache.set("fresh", "fresh")
        assert await cache.get("old") == "old"
        clock.advance(5)
        await cache.set("new", "new")
        assert await cache.get("fresh") == "fresh"
        assert await cache.get("old") is None
        assert len(cache._entries) == 2

    asyncio.run(exercise())


def test_default_clock_is_monotonic(monkeypatch):
    from app.services import cache as module

    clock = FakeClock()
    monkeypatch.setattr(module.time, "monotonic", clock)
    cache = MemorySummaryCache()

    async def exercise():
        await cache.set("key", "summary")
        clock.advance(300)
        assert await cache.get("key") is None

    asyncio.run(exercise())


def test_service_cache_hit_miss_expiry_and_normalized_input():
    clock = FakeClock()
    llm = FakeLLM()
    service = SummarizationService(llm, MemorySummaryCache(clock=clock), model_name="test-model")

    async def exercise():
        first = await service.summarize(SummarizeRequest(text="  Article\t\n  text.  "))
        second = await service.summarize(SummarizeRequest(text="Article text."))
        assert first.cached is False and second.cached is True
        assert first.summary == second.summary
        assert len(llm.messages) == 1
        assert llm.messages[0][1]["content"] == "Article text."
        clock.advance(300)
        third = await service.summarize(SummarizeRequest(text="Article text."))
        assert third.cached is False and third.status == "success"
        assert len(llm.messages) == 2

    asyncio.run(exercise())


def test_cache_key_is_sha256_of_only_normalized_text_length_model_and_prompt():
    service = SummarizationService(FakeLLM(), MemorySummaryCache(), model_name="test-model")
    request = SummarizeRequest(text="  Article\t text.  ", max_length=100)
    payload = json.dumps(
        ["test-model", PROMPT_VERSION, "Article text.", 100],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    key = service._cache_key(request)
    assert key == hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert len(key) == 64
    assert key == service._cache_key(SummarizeRequest(text="Article text.", max_length=100))


@pytest.mark.parametrize("change", ["text", "max_length", "model", "prompt"])
def test_parameter_changes_cause_real_cache_miss(change, monkeypatch):
    from app.services import summarizer

    cache = MemorySummaryCache()
    llm = FakeLLM()
    service = SummarizationService(llm, cache, model_name="model-a")

    async def exercise():
        request = SummarizeRequest(text="Article.", max_length=50)
        assert (await service.summarize(request)).cached is False
        target = service
        if change == "text":
            request = SummarizeRequest(text="Other article.", max_length=50)
        elif change == "max_length":
            request = SummarizeRequest(text="Article.", max_length=100)
        elif change == "model":
            target = SummarizationService(llm, cache, model_name="model-b")
        else:
            monkeypatch.setattr(summarizer, "PROMPT_VERSION", "next")
        assert (await target.summarize(request)).cached is False
        assert len(llm.messages) == 2

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "error",
    [
        LLMUnavailableError(),
        LLMTimeoutError(),
        LLMAuthenticationError(),
        LLMInvalidResponseError(),
        RuntimeError("bug"),
    ],
)
def test_fallback_and_errors_never_enter_real_ttl_cache(error):
    llm = FakeLLM(error)
    service = SummarizationService(llm, MemorySummaryCache())
    request = SummarizeRequest(text="Article.")

    async def exercise():
        for _ in range(2):
            if isinstance(error, LLMUnavailableError):
                result = await service.summarize(request)
                assert result.status == "fallback" and result.cached is False
            else:
                with pytest.raises(type(error)):
                    await service.summarize(request)
        assert len(llm.messages) == 2
        llm.error = None
        assert (await service.summarize(request)).cached is False
        assert (await service.summarize(request)).cached is True
        assert len(llm.messages) == 3

    asyncio.run(exercise())


def test_empty_generation_is_not_cached():
    llm = FakeLLM()
    cache = MemorySummaryCache()
    service = SummarizationService(llm, cache)

    async def empty(messages):
        return " \n\t"

    llm.generate = empty

    async def exercise():
        with pytest.raises(LLMInvalidResponseError):
            await service.summarize(SummarizeRequest(text="Article."))
        assert cache._entries == {}

    asyncio.run(exercise())


def test_concurrent_access_from_threads_and_async_tasks():
    cache = MemorySummaryCache(max_entries=32)

    def worker(index):
        async def exercise():
            key = str(index)
            await cache.set(key, key)
            assert await cache.get(key) == key

        asyncio.run(exercise())

    async def exercise():
        await asyncio.gather(*(asyncio.to_thread(worker, index) for index in range(32)))
        assert len(cache._entries) == 32
        assert await asyncio.gather(*(cache.get(str(index)) for index in range(32))) == [
            str(index) for index in range(32)
        ]

    asyncio.run(exercise())


def test_concurrent_writes_respect_capacity():
    cache = MemorySummaryCache(max_entries=8)

    async def exercise():
        await asyncio.gather(*(cache.set(str(index), str(index)) for index in range(100)))
        assert len(cache._entries) == 8
        assert await cache.get("0") is None
        assert await cache.get("99") == "99"

    asyncio.run(exercise())


@pytest.mark.parametrize("ttl", [0, -1, float("nan"), float("inf")])
def test_invalid_ttl_is_rejected(ttl):
    with pytest.raises(ValueError):
        MemorySummaryCache(ttl_seconds=ttl)


def test_invalid_capacity_is_rejected():
    with pytest.raises(ValueError):
        MemorySummaryCache(max_entries=0)
