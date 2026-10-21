import asyncio

import pytest

from app.llm.prompts import summary_messages
from app.models.summarize import SummarizeRequest
from app.services.cache import MemorySummaryCache
from app.services.summarizer import SummarizationService
from app.utils.errors import (
    InvalidProviderResponse,
    ProviderAuthenticationError,
    ProviderRejectedRequest,
    ProviderTimeout,
    ProviderUnavailable,
)


class FakeLLM:
    def __init__(self, output="  Summary.  ", error=None, events=None):
        self.output = output
        self.error = error
        self.calls = []
        self.events = events if events is not None else []

    async def generate(self, messages):
        self.calls.append(messages)
        self.events.append("llm")
        if self.error is not None:
            raise self.error
        return self.output


class FakeCache:
    def __init__(self, events=None):
        self.values = {}
        self.reads = []
        self.writes = []
        self.events = events if events is not None else []

    async def get(self, key):
        self.events.append("cache.get")
        self.reads.append(key)
        return self.values.get(key)

    async def set(self, key, summary):
        self.events.append("cache.set")
        self.writes.append((key, summary))
        self.values[key] = summary


def test_pipeline_orders_cache_prompt_llm_postprocessing_and_write(monkeypatch):
    from app.services import summarizer

    events = []
    llm = FakeLLM("  First   line.\r\n\r\n \t\n Second\tline.  ", events=events)
    cache = FakeCache(events)
    original_prompt = summarizer.summary_messages
    original_postprocess = summarizer.limit_summary

    def prompt(text, max_length):
        events.append("prompt")
        return original_prompt(text, max_length)

    def postprocess(text, max_length):
        events.append("postprocess")
        return original_postprocess(text, max_length)

    monkeypatch.setattr(summarizer, "summary_messages", prompt)
    monkeypatch.setattr(summarizer, "limit_summary", postprocess)
    request = SummarizeRequest(text="  Article.  ", max_length=50)
    result = asyncio.run(SummarizationService(llm, cache).summarize(request))
    assert events == ["cache.get", "prompt", "llm", "postprocess", "cache.set"]
    assert llm.calls == [summary_messages("Article.", 50)]
    assert result.model_dump() == {
        "summary": "First line.\nSecond line.",
        "status": "success",
        "cached": False,
    }
    assert cache.writes == [(cache.reads[0], result.summary)]
    assert "Article." not in cache.reads[0]


def test_cache_hit_skips_prompt_llm_and_postprocessing(monkeypatch):
    from app.services import summarizer

    llm, cache = FakeLLM(), FakeCache()
    service = SummarizationService(llm, cache)
    request = SummarizeRequest(text="Article.")

    async def exercise():
        first = await service.summarize(request)

        def forbidden(*args):
            raise AssertionError("Cached result must bypass prompt and postprocessing")

        monkeypatch.setattr(summarizer, "summary_messages", forbidden)
        monkeypatch.setattr(summarizer, "limit_summary", forbidden)
        second = await service.summarize(request)
        assert first.cached is False
        assert second.model_dump() == {
            "summary": first.summary,
            "status": "success",
            "cached": True,
        }

    asyncio.run(exercise())
    assert len(llm.calls) == len(cache.writes) == 1
    assert len(cache.reads) == 2


@pytest.mark.parametrize(
    "second",
    [
        {"text": "Different article.", "max_length": 50},
        {"text": "Article.", "max_length": 100},
    ],
)
def test_cache_key_includes_text_and_length(second):
    llm, cache = FakeLLM(), FakeCache()
    service = SummarizationService(llm, cache)

    async def exercise():
        await service.summarize(SummarizeRequest(text="Article.", max_length=50))
        result = await service.summarize(SummarizeRequest(**second))
        assert result.cached is False

    asyncio.run(exercise())
    assert len(set(cache.reads)) == len(llm.calls) == len(cache.writes) == 2


def test_cache_key_includes_prompt_version_and_model_namespace(monkeypatch):
    from app.services import summarizer

    llm, cache = FakeLLM(), FakeCache()
    request = SummarizeRequest(text="Article.")

    async def exercise():
        await SummarizationService(llm, cache, model_name="model-a").summarize(request)
        await SummarizationService(llm, cache, model_name="model-b").summarize(request)
        monkeypatch.setattr(summarizer, "PROMPT_VERSION", "next-version")
        await SummarizationService(llm, cache, model_name="model-a").summarize(request)

    asyncio.run(exercise())
    assert len(set(cache.reads)) == len(llm.calls) == 3


def test_validated_trimmed_text_shares_cache_key():
    llm, cache = FakeLLM(), FakeCache()
    service = SummarizationService(llm, cache)

    async def exercise():
        await service.summarize(SummarizeRequest(text=" Article. "))
        assert (await service.summarize(SummarizeRequest(text="Article."))).cached is True

    asyncio.run(exercise())
    assert len(llm.calls) == 1


@pytest.mark.parametrize(
    "error",
    [
        ProviderUnavailable("private details"),
        ProviderTimeout("private timeout"),
    ],
)
@pytest.mark.parametrize("text", ["Short article.", "Long article. " * 50])
def test_unavailability_returns_explicit_fallback_and_never_caches(error, text):
    llm, cache = FakeLLM(error=error), FakeCache()
    service = SummarizationService(llm, cache)
    request = SummarizeRequest(text=text, max_length=50)

    async def exercise():
        for _ in range(2):
            result = await service.summarize(request)
            assert result.status == "fallback"
            assert result.cached is False
            assert 0 < len(result.summary) <= 50
            assert result.summary == (text if len(text) <= 50 else text[:49].rstrip() + "…")
            assert "private" not in result.summary

    asyncio.run(exercise())
    assert len(llm.calls) == 2
    assert cache.writes == []
    assert cache.values == {}


def test_recovery_after_fallback_can_be_cached():
    llm, cache = FakeLLM(error=ProviderUnavailable()), FakeCache()
    service = SummarizationService(llm, cache)
    request = SummarizeRequest(text="Article.")

    async def exercise():
        assert (await service.summarize(request)).status == "fallback"
        llm.error = None
        assert (await service.summarize(request)).cached is False
        assert (await service.summarize(request)).cached is True

    asyncio.run(exercise())
    assert len(llm.calls) == 2
    assert len(cache.writes) == 1


@pytest.mark.parametrize("output", ["", " \t\n", "\r\n\r\n", "\u00a0"])
def test_empty_output_raises_and_never_caches(output):
    llm, cache = FakeLLM(output), FakeCache()
    with pytest.raises(InvalidProviderResponse):
        asyncio.run(SummarizationService(llm, cache).summarize(SummarizeRequest(text="Article.")))
    assert cache.writes == []


@pytest.mark.parametrize(
    "error",
    [
        InvalidProviderResponse("bad JSON"),
        ProviderRejectedRequest("rejected"),
        ProviderAuthenticationError("private credentials"),
        RuntimeError("bug"),
        asyncio.CancelledError(),
    ],
)
def test_other_errors_propagate_without_fallback_or_cache(error):
    llm, cache = FakeLLM(error=error), FakeCache()
    with pytest.raises(type(error)):
        asyncio.run(SummarizationService(llm, cache).summarize(SummarizeRequest(text="Article.")))
    assert cache.writes == []


@pytest.mark.parametrize("length", [49, 50, 51, 1000])
def test_postprocessed_summary_respects_length_and_is_what_gets_cached(length):
    llm, cache = FakeLLM("x" * length), FakeCache()
    result = asyncio.run(
        SummarizationService(llm, cache).summarize(SummarizeRequest(text="Article.", max_length=50))
    )
    assert result.summary == ("x" * length if length <= 50 else "x" * 49 + "…")
    assert result.status == "success"
    assert cache.writes[0][1] == result.summary


def test_memory_cache_evicts_least_recently_used_entry():
    async def exercise():
        cache = MemorySummaryCache(max_entries=2)
        await cache.set("a", "A")
        await cache.set("b", "B")
        assert await cache.get("a") == "A"
        await cache.set("c", "C")
        assert await cache.get("b") is None
        assert await cache.get("a") == "A"
        assert await cache.get("c") == "C"

    asyncio.run(exercise())


def test_cache_failure_does_not_turn_into_llm_fallback():
    class BrokenCache(FakeCache):
        async def get(self, key):
            raise RuntimeError("cache unavailable")

    llm = FakeLLM()
    with pytest.raises(RuntimeError, match="cache unavailable"):
        asyncio.run(
            SummarizationService(llm, BrokenCache()).summarize(SummarizeRequest(text="Article."))
        )
    assert llm.calls == []
