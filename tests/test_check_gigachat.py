import asyncio

import pytest

from app.utils.errors import ProviderAuthenticationError, ProviderTimeout
from scripts import check_gigachat


@pytest.mark.parametrize("error", [None, ProviderAuthenticationError, ProviderTimeout])
def test_manual_check_does_not_print_key_or_raw_errors(settings, monkeypatch, capsys, error):
    monkeypatch.setattr(check_gigachat.logging, "disable", lambda level: None)
    monkeypatch.setattr(check_gigachat.getpass, "getpass", lambda prompt: "private-input-key")

    def configured_settings(**kwargs):
        assert kwargs == {"auth_key": "private-input-key"}
        return settings

    async def check(config):
        assert config is settings
        if error is not None:
            raise error("private-input-key and private-bearer-token")
        print("GigaChat integration OK.")

    monkeypatch.setattr(check_gigachat, "Settings", configured_settings)
    monkeypatch.setattr(check_gigachat, "check", check)
    assert check_gigachat.main() == (0 if error is None else 1)
    output = capsys.readouterr()
    assert "private-input-key" not in output.out + output.err
    assert "private-bearer-token" not in output.out + output.err
    assert "Traceback" not in output.out + output.err


def test_manual_check_calls_llm_without_business_fallback(settings, monkeypatch, capsys):
    from contextlib import asynccontextmanager

    class StubLLM:
        async def summarize(self, text, max_length):
            assert max_length == 150
            assert "GigaChat" in text
            return "Short summary."

    @asynccontextmanager
    async def open_client(config):
        assert config is settings
        yield StubLLM()

    monkeypatch.setattr(check_gigachat, "open_gigachat", open_client)
    asyncio.run(check_gigachat.check(settings))
    assert capsys.readouterr().out == "GigaChat integration OK.\nShort summary.\n"


@pytest.mark.parametrize(
    ("status", "operation", "expected"),
    [
        (None, None, "stage=unknown, HTTP status unavailable"),
        (302, "oauth", "stage=oauth, HTTP 302"),
        (404, "completion", "stage=completion, HTTP 404"),
        ("private-status", "private-operation", "stage=unknown, HTTP status unavailable"),
    ],
)
def test_generic_provider_error_is_safe_and_actionable(
    settings, monkeypatch, capsys, status, operation, expected
):
    from app.utils.errors import LLMServiceError

    monkeypatch.setattr(check_gigachat.logging, "disable", lambda level: None)
    monkeypatch.setattr(check_gigachat.getpass, "getpass", lambda prompt: "private-key")
    monkeypatch.setattr(check_gigachat, "Settings", lambda **kwargs: settings)

    async def rejected(config):
        raise LLMServiceError(
            "private-key private-token private-response Authorization",
            status_code=status,
            operation=operation,
        )

    monkeypatch.setattr(check_gigachat, "check", rejected)
    assert check_gigachat.main() == 1
    output = capsys.readouterr()
    assert expected in output.out
    assert "redirects are not followed" in output.out
    assert "Traceback" not in output.out + output.err
    assert "private-" not in output.out + output.err
    assert "Authorization" not in output.out + output.err


def test_unexpected_programming_error_is_not_hidden(settings, monkeypatch):
    monkeypatch.setattr(check_gigachat.logging, "disable", lambda level: None)
    monkeypatch.setattr(check_gigachat.getpass, "getpass", lambda prompt: "fixture-key")
    monkeypatch.setattr(check_gigachat, "Settings", lambda **kwargs: settings)

    async def broken(config):
        raise RuntimeError("implementation defect")

    monkeypatch.setattr(check_gigachat, "check", broken)
    with pytest.raises(RuntimeError, match="implementation defect"):
        check_gigachat.main()
