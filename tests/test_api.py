import asyncio

import httpx
import pytest

from app.api.routes import get_summarizer
from app.config.settings import Settings
from app.llm.gigachat import GigaChatClient
from app.services.cache import MemorySummaryCache
from app.services.summarizer import SummarizationService
from app.utils.errors import (
    InvalidProviderResponse,
    LLMAuthenticationError,
    ProviderRejectedRequest,
    ProviderTimeout,
    ProviderUnavailable,
)
from main import create_app


class StubLLM:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, int]] = []

    async def generate(self, messages) -> str:
        import re

        text = messages[1]["content"]
        max_length = int(re.search(r"не более (\d+) символов", messages[0]["content"])[1])
        self.calls.append((text, max_length))
        if self.error:
            raise self.error
        return "  Краткое   содержание.\r\nВторая строка.  "


def make_app(llm: StubLLM):
    app = create_app()
    app.dependency_overrides[get_summarizer] = lambda: SummarizationService(
        llm, MemorySummaryCache()
    )
    return app


def post(app, payload):
    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post("/summarize", json=payload)

    return asyncio.run(exercise())


def test_success_and_postprocessing():
    llm = StubLLM()
    response = post(make_app(llm), {"text": "  Исходный текст.  "})
    assert response.status_code == 200
    assert response.json() == {
        "summary": "Краткое содержание.\nВторая строка.",
        "status": "success",
        "cached": False,
    }
    assert llm.calls == [("Исходный текст.", 300)]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"text": ""},
        {"text": " \t\n"},
        {"text": 42},
        {"text": None},
        {"text": "x" * 10001},
        {"text": "   "},
        {"text": "\u00a0\u2003"},
        {"text": []},
        {"text": True},
        *[
            {"text": "valid", "max_length": value}
            for value in (
                49,
                1001,
                0,
                -1,
                None,
                "300",
                300.0,
                300.5,
                True,
                False,
                [],
                {},
            )
        ],
        {"text": "valid", "extra": True},
    ],
)
def test_invalid_input_never_reaches_llm(payload):
    llm = StubLLM()
    response = post(make_app(llm), payload)
    assert response.status_code == 422
    assert llm.calls == []


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (InvalidProviderResponse, 502),
        (LLMAuthenticationError, 502),
        (ProviderRejectedRequest, 422),
    ],
)
def test_safe_error_mapping(error, status):
    response = post(make_app(StubLLM(error("secret provider payload"))), {"text": "Text"})
    assert response.status_code == status
    assert "secret" not in response.text
    assert isinstance(response.json()["detail"], str)


@pytest.mark.parametrize("provider_unavailable", [False, True])
def test_full_pipeline_with_mock_provider(settings: Settings, provider_unavailable):
    app = create_app(settings)

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == str(settings.auth_url):
            return httpx.Response(
                200,
                json={
                    "access_token": "token",
                    "expires_at": 9999999999999,
                },
            )
        if provider_unavailable:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": "  Готовое   резюме. "},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    async def exercise():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                app.state.summarizer = SummarizationService(
                    GigaChatClient(http, settings), MemorySummaryCache()
                )
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test"
                ) as api:
                    response = await api.post("/summarize", json={"text": "Текст статьи"})
                    assert response.status_code == (503 if provider_unavailable else 200)
                    assert response.json() == {
                        "summary": "Текст статьи" if provider_unavailable else "Готовое резюме.",
                        "status": "fallback" if provider_unavailable else "success",
                        "cached": False,
                    }
                    health = await api.get("/health")
                    assert health.status_code == 200
                    assert health.json() == {"status": "ok"}
                    assert (await api.get("/openapi.json")).status_code == 200

    asyncio.run(exercise())


@pytest.mark.parametrize("max_length", [50, 300, 1000])
@pytest.mark.parametrize("text", ["x", "x" * 10000, "  " + "x" * 10000 + "\t\n"])
def test_valid_boundaries_and_max_length_forwarded(text, max_length):
    llm = StubLLM()
    response = post(make_app(llm), {"text": text, "max_length": max_length})
    assert response.status_code == 200
    assert len(response.json()["summary"]) <= max_length
    assert llm.calls == [(text.strip(), max_length)]


@pytest.mark.parametrize("error", [ProviderUnavailable, ProviderTimeout])
def test_fallback_returns_503_and_safe_bounded_excerpt(error):
    llm = StubLLM(error("private provider details"))
    text = "Article " * 30
    response = post(make_app(llm), {"text": text, "max_length": 50})
    assert response.status_code == 503
    assert response.json() == {
        "summary": text[:49].rstrip() + "…",
        "status": "fallback",
        "cached": False,
    }
    assert "private" not in response.text
    assert llm.calls == [(text.strip(), 50)]


def test_health_does_not_resolve_business_service_or_call_llm():
    app = create_app()

    def forbidden_service():
        raise AssertionError("Health must not resolve the business service")

    app.dependency_overrides[get_summarizer] = forbidden_service

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health")
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}

    asyncio.run(exercise())


@pytest.mark.parametrize("body", [b"", b"{", b"null", b"[]"])
def test_missing_or_malformed_body_is_422(body):
    llm = StubLLM()

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=make_app(llm)), base_url="http://test"
        ) as client:
            response = await client.post(
                "/summarize", content=body, headers={"Content-Type": "application/json"}
            )
            assert response.status_code == 422

    asyncio.run(exercise())
    assert llm.calls == []


def test_dependency_injection_accepts_business_service_without_llm():
    from app.models.summarize import SummarizeResponse

    class Service:
        async def summarize(self, request):
            assert (request.text, request.max_length) == ("input", 50)
            return SummarizeResponse(summary="injected", status="success", cached=True)

    app = create_app()
    app.dependency_overrides[get_summarizer] = lambda: Service()
    response = post(app, {"text": "input", "max_length": 50})
    assert response.status_code == 200
    assert response.json() == {"summary": "injected", "status": "success", "cached": True}


def test_api_reports_real_cache_hit():
    llm = StubLLM()
    service = SummarizationService(llm, MemorySummaryCache())
    app = create_app()
    app.dependency_overrides[get_summarizer] = lambda: service
    first = post(app, {"text": "Article."})
    second = post(app, {"text": "Article."})
    assert first.status_code == second.status_code == 200
    assert first.json()["cached"] is False
    assert second.json()["cached"] is True
    assert second.json()["status"] == "success"
    assert len(llm.calls) == 1
