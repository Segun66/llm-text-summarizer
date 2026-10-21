"""Manual integration check: python -m scripts.check_gigachat (never run in unit tests)."""

import asyncio
import getpass
import logging

from pydantic import ValidationError

from app.config.settings import Settings
from app.llm.factory import open_gigachat
from app.utils.errors import (
    InvalidProviderResponse,
    ProviderAuthenticationError,
    ProviderRejectedRequest,
    ProviderTimeout,
    ProviderUnavailable,
)


async def check(settings: Settings) -> None:
    async with open_gigachat(settings) as llm:
        summary = await llm.summarize(
            "Команда выпустила HTTP API для сокращения текста. "
            "Сервис проверяет входные данные и использует GigaChat.",
            max_length=150,
        )
    print("GigaChat integration OK.")
    print(summary)


def main() -> int:
    # No HTTP debug logging, raw exceptions or settings dumps in this manual check.
    logging.disable(logging.CRITICAL)
    try:
        key = getpass.getpass("GigaChat authorization key (hidden): ")
        settings = Settings(auth_key=key)
        asyncio.run(check(settings))
    except (ValidationError, OSError):
        print("Configuration/TLS error: check endpoints, key and CA bundle.")
        return 1
    except ProviderAuthenticationError:
        print("GigaChat authorization failed: check the key and scope.")
        return 1
    except ProviderTimeout:
        print("GigaChat timed out.")
        return 1
    except ProviderUnavailable:
        print("GigaChat is unavailable or rate-limited.")
        return 1
    except ProviderRejectedRequest:
        print("GigaChat rejected the request: check model and input limits.")
        return 1
    except InvalidProviderResponse:
        print("GigaChat returned an invalid, empty or incomplete response.")
        return 1
    except (KeyboardInterrupt, EOFError):
        print("Cancelled.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
