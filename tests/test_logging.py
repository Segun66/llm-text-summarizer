import asyncio
import io
import json
import logging
import sys
from uuid import uuid4

import httpx
import pytest

from app.api.routes import get_summarizer
from app.llm.gigachat import GigaChatClient
from app.services.cache import MemorySummaryCache
from app.services.summarizer import SummarizationService
from app.utils.logging import JsonFormatter, configure_logging, request_id_context
from main import create_app


@pytest.fixture
def log_stream():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter("prod"))
    logger = logging.getLogger("app")
    original = (logger.handlers[:], logger.level, logger.propagate)
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    try:
        yield stream
    finally:
        logger.handlers, level, logger.propagate = original
        logger.setLevel(level)


def records(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_formatter_drops_messages_args_extra_and_exception_payload():
    secret = "fixture-private-key"
    try:
        raise ValueError(secret)
    except ValueError:
        record = logging.LogRecord("httpx", logging.ERROR, "", 1, "%s", (secret,), sys.exc_info())
    record.headers = {"Authorization": secret}
    record.text = "fixture-user-text"
    record.access_token = "fixture-access-token"
    record.request_id = secret
    output = JsonFormatter("prod").format(record)
    event = json.loads(output)
    assert event["event"] == "external_log"
    assert event["error_type"] == "ValueError"
    assert event["request_id"] == "-"
    for value in (secret, "Authorization", "fixture-user-text", "fixture-access-token"):
        assert value not in output


def test_request_context_isolated_and_pipeline_logs_are_safe(log_stream):
    class EchoLLM:
        async def generate(self, messages):
            await asyncio.sleep(0)
            return messages[1]["content"]

    service = SummarizationService(EchoLLM(), MemorySummaryCache())
    app = create_app()
    app.dependency_overrides[get_summarizer] = lambda: service
    ids = [str(uuid4()), str(uuid4())]
    texts = ["fixture-user-text-one", "fixture-user-text-two"]

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:

            async def post(index):
                return await client.post(
                    "/summarize",
                    json={"text": texts[index]},
                    headers={
                        "X-Request-ID": ids[index],
                        "Authorization": "fixture-client-header",
                    },
                )

            responses = await asyncio.gather(post(0), post(1))
            assert [response.headers["x-request-id"] for response in responses] == ids
            cached = await post(0)
            assert cached.json()["cached"] is True
            invalid = await client.post(
                "/summarize?token=fixture-query-secret",
                json={"text": ""},
                headers={"X-Request-ID": "fixture-invalid-id"},
            )
            assert invalid.status_code == 422
            assert invalid.headers["x-request-id"] != "fixture-invalid-id"
        assert request_id_context.get() == "-"

    asyncio.run(exercise())
    events = records(log_stream)
    for request_id in ids:
        associated = [event for event in events if event["request_id"] == request_id]
        assert any(event["event"] == "pipeline_finished" for event in associated)
        assert any(
            event["event"] == "request_finished" and event["status_code"] == 200
            for event in associated
        )
    assert {"hit", "miss"} <= {event.get("cache_status") for event in events}
    assert any(event["stage"] == "postprocessing" and "duration_ms" in event for event in events)
    assert any(event["event"] == "validation_error" for event in events)
    for value in (*texts, "fixture-client-header", "fixture-query-secret", "Authorization"):
        assert value not in log_stream.getvalue()


def test_retry_logs_attempt_and_safe_error_type(settings, log_stream):
    calls = 0

    def handler(request):
        nonlocal calls
        if str(request.url) == str(settings.auth_url):
            return httpx.Response(
                200,
                json={
                    "access_token": "fixture-private-token",
                    "expires_at": 9999999999999,
                },
            )
        calls += 1
        if calls < 3:
            return httpx.Response(429, text="fixture-private-response")
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

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            await GigaChatClient(http, settings).summarize("fixture-private-source")

    asyncio.run(exercise())
    retries = [event for event in records(log_stream) if event["event"] == "llm_retry"]
    assert [event["attempt"] for event in retries] == [1, 2]
    assert [event["next_attempt"] for event in retries] == [2, 3]
    assert all(event["error_type"] == "LLMRateLimitError" for event in retries)
    for value in (
        "test-secret",
        "fixture-private-token",
        "fixture-private-response",
        "fixture-private-source",
    ):
        assert value not in log_stream.getvalue()


def test_expired_cache_is_logged_without_keys_or_values(log_stream):
    now = [0.0]
    cache = MemorySummaryCache(ttl_seconds=1, clock=lambda: now[0])

    async def exercise():
        await cache.set("fixture-private-key", "fixture-private-summary")
        now[0] = 1
        assert await cache.get("fixture-private-key") is None

    asyncio.run(exercise())
    assert records(log_stream)[0]["cache_status"] == "expired"
    assert "fixture-private" not in log_stream.getvalue()


@pytest.mark.parametrize(("level", "expected"), [("INFO", logging.INFO), ("DEBUG", logging.DEBUG)])
def test_logging_configuration(level, expected):
    names = ("", "app", "uvicorn", "uvicorn.error", "uvicorn.access", "httpx", "httpcore")
    snapshots = {
        name: (
            logging.getLogger(name).handlers[:],
            logging.getLogger(name).level,
            logging.getLogger(name).propagate,
        )
        for name in names
    }
    try:
        configure_logging(level, "prod")
        root = logging.getLogger()
        assert root.level == expected
        assert isinstance(root.handlers[0].formatter, JsonFormatter)
        assert root.handlers[0].formatter.app_env == "prod"
        assert logging.getLogger("uvicorn.error").handlers == []
        assert logging.getLogger("uvicorn.error").propagate is True
    finally:
        for name, (handlers, old_level, propagate) in snapshots.items():
            logger = logging.getLogger(name)
            logger.handlers = handlers
            logger.setLevel(old_level)
            logger.propagate = propagate
