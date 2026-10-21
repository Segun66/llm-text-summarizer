import re

from app.utils.errors import LLMInvalidResponseError


def clean_summary(text: str) -> str:
    """Normalize whitespace and remove empty lines without rewriting content."""
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in text.splitlines()]
    summary = "\n".join(line for line in lines if line)
    if not summary:
        raise LLMInvalidResponseError("Provider returned an empty summary")
    return summary


def limit_summary(text: str, max_length: int) -> str:
    """Normalize the text and cap its length, including the ellipsis."""
    summary = clean_summary(text)
    if len(summary) <= max_length:
        return summary
    return summary[: max_length - 1].rstrip() + "…"
