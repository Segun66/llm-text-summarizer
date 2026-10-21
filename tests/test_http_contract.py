"""Scenario audit using FastAPI TestClient and the real service/cache/LLM adapter."""

import io
import json
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

import main
from app.api.routes import get_summarizer
from app.llm.factory import open_gigachat
from app.services.cache import MemorySummaryCache
from app.utils.logging import JsonFormatter


class FakeClock:
    now = 0.0

    def __call__(self):
        return self.now


class ProviderDouble:
    def __init__(self, settings):
        self.settings = settings
        self.outcomes = ["success"]
        self.failure_phase = "completion"
        self.calls = {"oauth": 0, "completion": 0}

    def __call__(self, request):
        if str(request.url) == str(self.settings.auth_url):
            phase = "oauth"
        elif str(request.url) == str(self.settings.completions_url):
            phase = "completion"
        else:
            raise AssertionError("Unexpected endpoint")
        self.calls[phase] += 1
        outcome = "success"
        if phase == self.failure_phase:
            outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if outcome == "timeout":
            raise httpx.ReadTimeout("fixture-private-upstream-error", request=request)
        if outcome == "network":
            raise httpx.ConnectError("fixture-private-upstream-error", request=request)
        if isinstance(outcome, int):
            return httpx.Response(outcome, text="fixture-private-upstream-error")
        if outcome == "json":
            return httpx.Response(200, text="fixture-private-invalid-json")
        if outcome == "schema":
            return httpx.Response(200, json={"choices": []})
        if phase == "oauth":
            return httpx.Response(
                200,
                json={
                    "access_token": "fixture-private-access-token",
                    "expires_at": 9999999999999,
                },
            )
        content = {"empty": "", "whitespace": " \t\n", "null": None}.get(
            outcome, "  Short   summary.\n\n Second line.  "
        )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": content},
                        "finish_reason": outcome if outcome in {"length", "blacklist"} else "stop",
                    }
                ]
            },
        )


@pytest.fixture
def harness(settings, monkeypatch):
    """Run lifespan with a mock transport; restore all patched state on teardown."""
    clock = FakeClock()
    cache = MemorySummaryCache(ttl_seconds=300, clock=clock)
    provider = ProviderDouble(settings)
    opened = []
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter("dev"))
    logger = logging.getLogger("app")
    previous = (logger.handlers[:], logger.level, logger.propagate)
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    @asynccontextmanager
    async def mocked_factory(config):
        async with open_gigachat(config, transport=httpx.MockTransport(provider)) as llm:
            opened.append(llm)
            yield llm

    monkeypatch.setattr(main, "open_gigachat", mocked_factory)
    monkeypatch.setattr(main, "MemorySummaryCache", lambda **kwargs: cache)
    monkeypatch.setattr(main, "configure_logging", lambda *args: None)
    app = main.create_app(settings)
    try:
        with TestClient(app) as client:
            yield SimpleNamespace(
                client=client,
                app=app,
                provider=provider,
                clock=clock,
                cache=cache,
                logs=stream,
            )
        assert opened[0]._http.is_closed
    finally:
        logger.handlers, level, logger.propagate = previous
        logger.setLevel(level)


def test_valid_text_returns_200_success(harness):
    response = harness.client.post("/summarize", json={"text": "Valid article.", "max_length": 50})
    assert response.status_code == 200
    assert response.json() == {
        "summary": "Short summary.\nSecond line.",
        "status": "success",
        "cached": False,
    }
    assert 0 < len(response.json()["summary"]) <= 50
    assert harness.provider.calls == {"oauth": 1, "completion": 1}


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"text": ""}, id="empty"),
        pytest.param({"text": "   "}, id="spaces"),
        pytest.param({"text": "\t\n\u00a0"}, id="unicode-whitespace"),
        pytest.param({"text": "x" * 10001}, id="too-long"),
        pytest.param({}, id="missing-text"),
        *[
            pytest.param({"text": "Valid", "max_length": value}, id=f"max-length-{index}")
            for index, value in enumerate([49, 1001, 0, -1, "300", 300.0, True, None])
        ],
    ],
)
def test_input_validation_rejects_before_any_provider_call(harness, payload):
    response = harness.client.post("/summarize", json=payload)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert harness.provider.calls == {"oauth": 0, "completion": 0}
    assert harness.cache._entries == {}


@pytest.mark.parametrize("phase", ["oauth", "completion"])
@pytest.mark.parametrize("fault", ["timeout", "network", 429, 500])
def test_transient_failures_retry_then_fallback_never_cached(harness, phase, fault):
    harness.provider.failure_phase = phase
    harness.provider.outcomes = [fault]
    for index in range(2):
        response = harness.client.post("/summarize", json={"text": "Article.", "max_length": 50})
        assert response.status_code == 503
        assert response.json() == {
            "summary": "Article.",
            "status": "fallback",
            "cached": False,
        }
        assert harness.provider.calls[phase] == (index + 1) * 3
        assert harness.cache._entries == {}
    events = [json.loads(line) for line in harness.logs.getvalue().splitlines()]
    retries = [event for event in events if event["event"] == "llm_retry"]
    assert [event["attempt"] for event in retries] == [1, 2, 1, 2]


@pytest.mark.parametrize("phase", ["oauth", "completion"])
@pytest.mark.parametrize("status", [401, 403])
def test_authentication_failure_never_retried_or_cached(harness, phase, status):
    harness.provider.failure_phase = phase
    harness.provider.outcomes = [status]
    response = harness.client.post("/summarize", json={"text": "Article."})
    assert response.status_code == 502
    assert isinstance(response.json()["detail"], str)
    assert "fallback" not in response.text
    assert harness.provider.calls[phase] == 1
    assert harness.cache._entries == {}
    assert "llm_retry" not in harness.logs.getvalue()


@pytest.mark.parametrize("fault", ["timeout", "network", 429, 500])
def test_successful_retry_returns_success_then_cache_hit(harness, fault):
    harness.provider.outcomes = [fault, fault, "success"]
    first = harness.client.post("/summarize", json={"text": "Article."})
    second = harness.client.post("/summarize", json={"text": "Article."})
    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == second.json()["status"] == "success"
    assert first.json()["cached"] is False
    assert second.json()["cached"] is True
    assert harness.provider.calls["completion"] == 3


@pytest.mark.parametrize(
    "outcome", ["empty", "whitespace", "null", "json", "schema", "length", "blacklist"]
)
def test_invalid_model_response_is_502_without_retry_or_cache(harness, outcome):
    harness.provider.outcomes = [outcome]
    for index in range(2):
        response = harness.client.post("/summarize", json={"text": "Article."})
        assert response.status_code == 502
        assert isinstance(response.json()["detail"], str)
        assert harness.provider.calls["completion"] == index + 1
        assert harness.cache._entries == {}
    assert "llm_retry" not in harness.logs.getvalue()


def test_http_cache_miss_hit_exact_ttl_expiry(harness):
    first = harness.client.post("/summarize", json={"text": " Article. "})
    assert first.status_code == 200 and first.json()["cached"] is False
    harness.clock.now = 299.999
    second = harness.client.post("/summarize", json={"text": "Article."})
    assert second.status_code == 200 and second.json()["cached"] is True
    assert harness.provider.calls["completion"] == 1
    harness.clock.now = 300
    expired = harness.client.post("/summarize", json={"text": "Article."})
    assert expired.status_code == 200 and expired.json()["cached"] is False
    assert harness.provider.calls["completion"] == 2
    log_records = [json.loads(line) for line in harness.logs.getvalue().splitlines()]
    assert {"hit", "miss", "expired"} <= {event.get("cache_status") for event in log_records}


def test_no_secret_or_full_user_text_in_http_retry_logs(harness):
    harness.provider.outcomes = [429]
    request_id = str(uuid4())
    response = harness.client.post(
        "/summarize?secret=fixture-query-secret",
        json={"text": "fixture-full-private-user-text"},
        headers={"Authorization": "fixture-client-authorization", "X-Request-ID": request_id},
    )
    assert response.status_code == 503
    assert response.headers["x-request-id"] == request_id
    logs = harness.logs.getvalue()
    for secret in (
        "test-secret",
        "fixture-private-access-token",
        "fixture-client-authorization",
        "fixture-full-private-user-text",
        "fixture-private-upstream-error",
        "fixture-query-secret",
        "Authorization",
    ):
        assert secret not in logs
    request_events = [
        json.loads(line) for line in logs.splitlines() if json.loads(line)["event"] != "app_started"
    ]
    assert request_events
    assert all(event["request_id"] == request_id for event in request_events)


def test_health_works_without_llm_or_business_dependency(harness):
    harness.provider.outcomes = ["timeout"]

    def forbidden():
        raise AssertionError("Health must not resolve the business service")

    harness.app.dependency_overrides[get_summarizer] = forbidden
    response = harness.client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert harness.provider.calls == {"oauth": 0, "completion": 0}


def test_real_network_guard_blocks_default_httpx_transport():
    with httpx.Client() as client, pytest.raises(AssertionError, match="Real HTTP is forbidden"):
        client.get("https://must-not-be-contacted.test")
