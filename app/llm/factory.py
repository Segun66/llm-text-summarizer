import ssl
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from app.config.settings import Settings
from app.llm.gigachat import GigaChatClient


@asynccontextmanager
async def open_gigachat(
    settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
) -> AsyncIterator[GigaChatClient]:
    """Own the connection pool; injected clients/transports remain easy to test."""
    context = ssl.create_default_context(cafile=settings.certificate_path())
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(settings.timeout_seconds),
        verify=context,
        follow_redirects=False,
        transport=transport,
    ) as http:
        yield GigaChatClient(http, settings)
