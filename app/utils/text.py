def normalize_text(text: str) -> str:
    """Canonicalize whitespace without changing case or punctuation."""
    return " ".join(text.split())
