from __future__ import annotations

import re

_URL = re.compile(r"https?://[^\s'\"]+")
_SECRET_FIELD = re.compile(r"(?i)(api[_-]?key|token|authorization|private[_-]?key|api[_-]?hash)=([^&\s]+)")


def safe_error(exc: BaseException) -> str:
    """Return a short persistence-safe error without endpoint credentials."""
    name = type(exc).__name__
    message = str(exc).replace("\n", " ").strip()
    message = _URL.sub("<redacted-url>", message)
    message = _SECRET_FIELD.sub(r"\1=<redacted>", message)
    message = message[:240]
    return f"{name}: {message}" if message else name
