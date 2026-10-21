import pytest

from app.config.settings import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        auth_key="test-secret",
        auth_url="https://auth.test/oauth",
        completions_url="https://llm.test/completions",
        retry_min_seconds=0,
        retry_max_seconds=0,
    )


@pytest.fixture(autouse=True)
def disable_llm_retry_sleep(monkeypatch):
    from app.llm import gigachat

    original_retry = gigachat.AsyncRetrying

    async def no_sleep(delay):
        return None

    def without_delays(**kwargs):
        return original_retry(sleep=no_sleep, **kwargs)

    monkeypatch.setattr(gigachat, "AsyncRetrying", without_delays)


@pytest.fixture(autouse=True)
def block_real_httpx_network(monkeypatch):
    import httpx

    def blocked_sync(self, request):
        raise AssertionError("Real HTTP is forbidden in tests; use MockTransport")

    async def blocked_async(self, request):
        raise AssertionError("Real HTTP is forbidden in tests; use MockTransport")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked_sync)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", blocked_async)
