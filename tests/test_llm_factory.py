import asyncio
import ssl

import httpx
import pytest

from app.llm.factory import open_gigachat
from app.utils.errors import InvalidProviderResponse


@pytest.mark.parametrize("invalid_response", [False, True])
def test_factory_enforces_tls_and_closes_http_client(settings, monkeypatch, invalid_response):
    from app.llm import factory

    real_client = httpx.AsyncClient
    clients = []

    def capture_client(**kwargs):
        assert kwargs["verify"].verify_mode == ssl.CERT_REQUIRED
        assert kwargs["verify"].check_hostname is True
        assert kwargs["timeout"].read == settings.timeout_seconds
        assert kwargs["follow_redirects"] is False
        client = real_client(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(factory.httpx, "AsyncClient", capture_client)

    def handler(request):
        if str(request.url) == str(settings.auth_url):
            return httpx.Response(
                200,
                json={
                    "access_token": "token",
                    "expires_at": 9999999999999,
                },
            )
        if invalid_response:
            return httpx.Response(200, text="not json")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": "Summary"},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    async def exercise():
        if invalid_response:
            with pytest.raises(InvalidProviderResponse):
                async with open_gigachat(settings, transport=httpx.MockTransport(handler)) as llm:
                    assert not clients[0].is_closed
                    await llm.summarize("text")
        else:
            async with open_gigachat(settings, transport=httpx.MockTransport(handler)) as llm:
                assert not clients[0].is_closed
                assert await llm.summarize("text") == "Summary"
        assert clients[0].is_closed

    asyncio.run(exercise())
