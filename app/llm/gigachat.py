import asyncio
import time
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from app.config.settings import Settings
from app.llm.base import LLMMessage
from app.llm.prompts import summary_messages
from app.utils.errors import (
    LLMAuthenticationError,
    LLMInvalidResponseError,
    LLMNetworkError,
    LLMRateLimitError,
    LLMRequestError,
    LLMServiceError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.utils.logging import log_event


class _Token(BaseModel):
    model_config = ConfigDict(strict=True)

    access_token: SecretStr
    expires_at: int = Field(gt=0)


class _Message(BaseModel):
    content: str


class _Choice(BaseModel):
    message: _Message
    finish_reason: str


class _Completion(BaseModel):
    choices: list[_Choice] = Field(min_length=1)


class GigaChatClient:
    def __init__(self, http: httpx.AsyncClient, settings: Settings) -> None:
        self._http = http
        self._settings = settings
        self._token: _Token | None = None
        self._token_lock = asyncio.Lock()

    async def _request(
        self, url: str, *, headers: dict[str, str], oauth: bool, **kwargs: object
    ) -> httpx.Response:
        request_headers = headers.copy()
        if oauth:
            request_headers["RqUID"] = str(uuid4())
        try:
            response = await self._http.post(
                url, headers=request_headers, timeout=self._settings.timeout_seconds, **kwargs
            )
        except httpx.TimeoutException:
            raise LLMTimeoutError("Provider timed out") from None
        except (httpx.NetworkError, httpx.RemoteProtocolError, httpx.ProxyError):
            raise LLMNetworkError("Provider connection failed") from None

        status = response.status_code
        if status == 429:
            raise LLMRateLimitError("Provider rate limit exceeded")
        if 500 <= status < 600:
            raise LLMUnavailableError("Provider is unavailable")
        if status in {401, 403} or (oauth and status == 400):
            raise LLMAuthenticationError("Provider authorization failed")
        if status in {400, 413, 422}:
            raise LLMRequestError("Provider rejected the input")
        if not response.is_success:
            raise LLMServiceError(
                "Provider rejected the operation",
                status_code=status,
                operation="oauth" if oauth else "completion",
            )
        return response

    @staticmethod
    def _log_retry(state) -> None:
        error = state.outcome.exception()
        log_event(
            "llm_retry",
            "llm",
            attempt=state.attempt_number,
            next_attempt=state.attempt_number + 1,
            retry_in_seconds=state.next_action.sleep,
            error_type=type(error).__name__,
        )

    async def _post(
        self, url: str, *, headers: dict[str, str], oauth: bool = False, **kwargs: object
    ) -> httpx.Response:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(min(self._settings.max_attempts, 3)),
            wait=wait_random_exponential(
                multiplier=self._settings.retry_min_seconds,
                max=self._settings.retry_max_seconds,
            ),
            retry=retry_if_exception_type(LLMUnavailableError),
            reraise=True,
            before_sleep=self._log_retry,
        ):
            with attempt:
                return await self._request(url, headers=headers, oauth=oauth, **kwargs)
        raise RuntimeError("Unreachable retry state")

    async def _get_token(self) -> str:
        async with self._token_lock:
            token = self._token
            if token is not None and token.expires_at / 1000 > time.time() + 30:
                return token.access_token.get_secret_value()
            response = await self._post(
                str(self._settings.auth_url),
                headers={
                    "Authorization": f"Basic {self._settings.credentials.get_secret_value()}",
                    "Accept": "application/json",
                },
                oauth=True,
                data={"scope": self._settings.scope},
            )
            try:
                token = _Token.model_validate(response.json())
            except (ValidationError, ValueError):
                raise LLMInvalidResponseError("Provider returned an invalid access token") from None
            if (
                not token.access_token.get_secret_value().strip()
                or token.expires_at / 1000 <= time.time()
            ):
                raise LLMInvalidResponseError("Provider returned an invalid access token")
            self._token = token
            return token.access_token.get_secret_value()

    async def _complete(self, messages: list[LLMMessage], token: str) -> httpx.Response:
        return await self._post(
            str(self._settings.completions_url),
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            json={
                "model": self._settings.model,
                "messages": messages,
                "max_tokens": self._settings.max_tokens,
                "temperature": 0.2,
                "stream": False,
            },
        )

    async def summarize(self, text: str, max_length: int = 300) -> str:
        return await self.generate(summary_messages(text, max_length))

    async def generate(self, messages: list[LLMMessage]) -> str:
        token = await self._get_token()
        response = await self._complete(messages, token)
        try:
            completion = _Completion.model_validate(response.json())
        except (ValidationError, ValueError):
            raise LLMInvalidResponseError("Provider returned an invalid response") from None
        choice = completion.choices[0]
        if choice.finish_reason != "stop":
            raise LLMInvalidResponseError("Provider did not produce a complete summary")
        if not choice.message.content.strip():
            raise LLMInvalidResponseError("Provider returned an empty summary")
        return choice.message.content
