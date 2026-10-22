"""Regression checks added during the independent submission audit."""

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_summarizer
from app.llm.gigachat import GigaChatClient
from app.utils.errors import LLMServiceError, LLMUnavailableError
from main import create_app


@pytest.mark.parametrize(
    ("error", "status", "detail"),
    [
        (LLMUnavailableError("fixture-private-provider-error"), 503, "LLM временно недоступна."),
        (
            LLMServiceError("fixture-private-provider-error"),
            502,
            "Не удалось получить краткое содержание.",
        ),
    ],
)
def test_dependency_error_response_matches_openapi(error, status, detail):
    app = create_app()

    def failed_dependency():
        raise error

    app.dependency_overrides[get_summarizer] = failed_dependency
    client = TestClient(app)
    response = client.post("/summarize", json={"text": "Article."})
    assert response.status_code == status
    assert response.json() == {"detail": detail}
    assert "fixture-private" not in response.text
    schema = client.get("/openapi.json").json()["paths"]["/summarize"]["post"]["responses"][
        str(status)
    ]["content"]["application/json"]["schema"]
    alternatives = schema.get("anyOf", [schema])
    assert {"$ref": "#/components/schemas/ErrorResponse"} in alternatives


@pytest.mark.parametrize("phase", ["oauth", "completion"])
@pytest.mark.parametrize("status", [302, 404])
def test_other_provider_statuses_fail_without_retry_or_redirect(settings, phase, status):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        oauth = str(request.url) == str(settings.auth_url)
        if oauth == (phase == "oauth"):
            return httpx.Response(
                status, headers={"Location": "https://must-not-be-contacted.test"}
            )
        return httpx.Response(
            200, json={"access_token": "fixture-token", "expires_at": 9999999999999}
        )

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(LLMServiceError) as caught:
                await GigaChatClient(http, settings).summarize("Article.")
            assert type(caught.value) is LLMServiceError
            assert caught.value.status_code == status
            assert caught.value.operation == phase

    asyncio.run(exercise())
    failed_url = settings.auth_url if phase == "oauth" else settings.completions_url
    assert calls.count(str(failed_url)) == 1
    assert all("must-not-be-contacted" not in url for url in calls)
