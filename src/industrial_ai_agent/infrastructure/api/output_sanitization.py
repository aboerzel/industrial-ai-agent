"""Fail-safe public projection for text that may originate outside the API."""

import re
from typing import Any

_UNSAFE_PUBLIC_TEXT = re.compile(
    r"(traceback\s*\(most recent call last\)|"
    r"postgres(?:ql)?://|mongodb(?:\+srv)?://|"
    r"(?:password|api[_-]?key|secret|token)\s*[=:]|"
    r"\bsk-[A-Za-z0-9_-]{12,}|"
    r"[A-Za-z]:\\|/(?:home|users|var|tmp)/|"
    r"(?:langgraph )?checkpoint(?: data)?)",
    re.IGNORECASE,
)
_REDACTED_PUBLIC_TEXT = "The requested result contains non-public diagnostic data."


def sanitize_public_text(value: str | None) -> str | None:
    """Do not leak diagnostic internals through a successful public response."""
    if value is None or not _UNSAFE_PUBLIC_TEXT.search(value):
        return value
    return _REDACTED_PUBLIC_TEXT


def sanitize_public_value(value: Any) -> Any:
    """Recursively sanitize public JSON-compatible payloads without exposing raw state."""
    if isinstance(value, str):
        return sanitize_public_text(value)
    if isinstance(value, tuple):
        return tuple(sanitize_public_value(item) for item in value)
    if isinstance(value, list):
        return [sanitize_public_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): sanitize_public_value(item) for key, item in value.items()}
    return value
