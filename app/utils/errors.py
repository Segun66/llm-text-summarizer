from typing import Literal


class LLMServiceError(Exception):
    """Safe provider-independent LLM failure; never include secrets in messages."""

    def __init__(
        self,
        message: str = "",
        *,
        status_code: int | None = None,
        operation: Literal["oauth", "completion"] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.operation = operation


class LLMUnavailableError(LLMServiceError):
    """Transient provider failure, including upstream 5xx."""


class LLMTimeoutError(LLMUnavailableError):
    pass


class LLMNetworkError(LLMUnavailableError):
    pass


class LLMRateLimitError(LLMUnavailableError):
    pass


class LLMAuthenticationError(LLMServiceError):
    """Permanent provider authentication/access failure; never retry or fallback."""


class LLMInvalidResponseError(LLMServiceError):
    pass


class LLMRequestError(LLMServiceError):
    """Provider rejected the request; retrying unchanged input will not help."""


# Compatibility names for callers using the original exception imports.
SummarizationError = LLMServiceError
ProviderUnavailable = LLMUnavailableError
ProviderTimeout = LLMTimeoutError
ProviderAuthenticationError = LLMAuthenticationError
InvalidProviderResponse = LLMInvalidResponseError
ProviderRejectedRequest = LLMRequestError
