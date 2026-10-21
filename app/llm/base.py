from typing import Literal, Protocol, TypedDict


class LLMMessage(TypedDict):
    role: Literal["system", "user"]
    content: str


class LLMClient(Protocol):
    async def generate(self, messages: list[LLMMessage]) -> str: ...


class SummaryLLM(Protocol):
    """Convenience interface for direct integration checks."""

    async def summarize(self, text: str, max_length: int = 300) -> str: ...
