class LLMServiceError(Exception):
    """Safe provider-independent LLM failure; never include secrets in messages."""


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
