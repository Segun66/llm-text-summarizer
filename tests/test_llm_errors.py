import asyncio

import httpx
import pytest

from app.api.routes import get_summarizer
from app.llm.gigachat import GigaChatClient
from app.models.summarize import SummarizeRequest
from app.services.summarizer import SummarizationService
from app.utils.errors import (
    LLMAuthenticationError,
    LLMInvalidResponseError,
    LLMNetworkError,
    LLMRateLimitError,
    LLMRequestError,
    LLMServiceError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from main import create_app


class FakeCache:
    def __init__(self):
        self.writes = []

    async def get(self, key):
        return None

    async def set(self, key, summary):
        self.writes.append((key, summary))


def oauth_response():
    return httpx.Response(200, json={"access_token": "token", "expires_at": 9999999999999})


def completion_response():
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {"content": "Summary."},
                    "finish_reason": "stop",
                }
            ]
        },
    )


def failure(request, fault):
    if fault == "timeout":
        raise httpx.ReadTimeout("private network details", request=request)
    if fault == "network":
        raise httpx.ConnectError("private connection details", request=request)
    if fault == "json":
        return httpx.Response(200, text="not json")
    return httpx.Response(fault, text="private provider details")


@pytest.mark.parametrize("phase", ["oauth", "completion"])
@pytest.mark.parametrize(
    ("fault", "error", "attempts"),
    [
        ("timeout", LLMTimeoutError, 3),
        ("network", LLMNetworkError, 3),
        (429, LLMRateLimitError, 3),
        (500, LLMUnavailableError, 3),
        (401, LLMAuthenticationError, 1),
        (403, LLMAuthenticationError, 1),
        ("json", LLMInvalidResponseError, 1),
    ],
)
def test_typed_error_and_retry_exhaustion(settings, phase, fault, error, attempts):
    calls = 0

    def handler(request):
        nonlocal calls
        oauth = str(request.url) == str(settings.auth_url)
        if oauth == (phase == "oauth"):
            calls += 1
            return failure(request, fault)
        return oauth_response() if oauth else completion_response()

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(error):
                await GigaChatClient(http, settings).summarize("Article.")

    asyncio.run(exercise())
    assert calls == attempts


@pytest.mark.parametrize("fault", ["timeout", "network", 429, 500])
def test_successful_retry_is_cached_only_after_postprocessing(settings, fault):
    calls = 0
    cache = FakeCache()

    def handler(request):
        nonlocal calls
        if str(request.url) == str(settings.auth_url):
            return oauth_response()
        calls += 1
        if calls < 3:
            return failure(request, fault)
        return completion_response()

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            service = SummarizationService(GigaChatClient(http, settings), cache)
            result = await service.summarize(SummarizeRequest(text="Article."))
            assert result.status == "success" and result.cached is False
            assert cache.writes == [(cache.writes[0][0], "Summary.")]

    asyncio.run(exercise())
    assert calls == 3


@pytest.mark.parametrize("phase", ["oauth", "completion"])
@pytest.mark.parametrize("fault", ["timeout", "network", 429, 500])
def test_fallback_after_retries_is_503_and_never_cached(settings, phase, fault):
    calls = 0
    cache = FakeCache()

    def handler(request):
        nonlocal calls
        oauth = str(request.url) == str(settings.auth_url)
        if oauth == (phase == "oauth"):
            calls += 1
            return failure(request, fault)
        return oauth_response() if oauth else completion_response()

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            app = create_app(settings)
            service = SummarizationService(GigaChatClient(http, settings), cache)
            app.dependency_overrides[get_summarizer] = lambda: service
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as api:
                for _ in range(2):
                    response = await api.post("/summarize", json={"text": "Article."})
                    assert response.status_code == 503
                    assert response.json() == {
                        "summary": "Article.",
                        "status": "fallback",
                        "cached": False,
                    }

    asyncio.run(exercise())
    assert calls == 6
    assert cache.writes == []


@pytest.mark.parametrize("status", [400, 401, 403, 422])
def test_permanent_error_is_not_retried_or_fallback_or_cached(settings, status):
    calls = 0
    cache = FakeCache()

    def handler(request):
        nonlocal calls
        if str(request.url) == str(settings.auth_url):
            return oauth_response()
        calls += 1
        return httpx.Response(status)

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            app = create_app(settings)
            service = SummarizationService(GigaChatClient(http, settings), cache)
            app.dependency_overrides[get_summarizer] = lambda: service
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as api:
                response = await api.post("/summarize", json={"text": "Article."})
                assert response.status_code == (502 if status in {401, 403} else 422)
                assert "detail" in response.json()
                assert "fallback" not in response.text

    asyncio.run(exercise())
    assert calls == 1 and cache.writes == []


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("bug"),
        ValueError("bug"),
        httpx.LocalProtocolError("invalid local request"),
    ],
)
def test_programming_errors_are_never_retried_or_fallback(settings, error):
    calls = 0
    cache = FakeCache()

    def handler(request):
        nonlocal calls
        calls += 1
        raise error

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            service = SummarizationService(GigaChatClient(http, settings), cache)
            with pytest.raises(type(error)):
                await service.summarize(SummarizeRequest(text="Article."))

    asyncio.run(exercise())
    assert calls == 1 and cache.writes == []


def test_error_hierarchy_keeps_authentication_outside_transient_failures():
    for error in (LLMTimeoutError, LLMNetworkError, LLMRateLimitError, LLMUnavailableError):
        assert issubclass(error, LLMServiceError)
        assert issubclass(error, LLMUnavailableError)
    assert issubclass(LLMAuthenticationError, LLMServiceError)
    assert not issubclass(LLMAuthenticationError, LLMUnavailableError)
    assert not issubclass(LLMInvalidResponseError, LLMUnavailableError)


def test_400_completion_maps_to_request_error(settings):
    def handler(request):
        return (
            oauth_response() if str(request.url) == str(settings.auth_url) else httpx.Response(400)
        )

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(LLMRequestError):
                await GigaChatClient(http, settings).summarize("Article.")

    asyncio.run(exercise())


@pytest.mark.parametrize("error", [RuntimeError("bug"), ValueError("bug")])
def test_programming_error_reaches_api_as_500_without_cache(error):
    cache = FakeCache()

    class BrokenLLM:
        async def generate(self, messages):
            raise error

    async def exercise():
        app = create_app()
        service = SummarizationService(BrokenLLM(), cache)
        app.dependency_overrides[get_summarizer] = lambda: service
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as api:
            response = await api.post("/summarize", json={"text": "Article."})
            assert response.status_code == 500
            assert "fallback" not in response.text

    asyncio.run(exercise())
    assert cache.writes == []
