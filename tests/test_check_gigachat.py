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
