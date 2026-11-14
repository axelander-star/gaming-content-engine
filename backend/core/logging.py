"""Structured JSON logging with secret masking."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

_SENSITIVE_KEYS = re.compile(r"(password|secret|token|api_key|apikey|authorization)", re.I)
_SENSITIVE_INLINE = re.compile(
    r"(?i)\b(password|secret|token|api_key|apikey)\b(\s*[=:]\s*)([^\s,;]+)"
)
_URL_CREDENTIALS = re.compile(r"(://[^:/@\s]+:)([^@\s]+)(@)")
MASK = "***"
_RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


def mask_text(text: str) -> str:
    """Hide credentials embedded in free text (key=value pairs, URLs)."""
    text = _URL_CREDENTIALS.sub(rf"\1{MASK}\3", text)
    return _SENSITIVE_INLINE.sub(rf"\1\2{MASK}", text)


def mask_value(key: str, value: Any) -> Any:
    """Mask a structured field if its key looks sensitive."""
    if _SENSITIVE_KEYS.search(key):
        return MASK
    if isinstance(value, dict):
        return {k: mask_value(str(k), v) for k, v in value.items()}
    if isinstance(value, str):
        return mask_text(value)
    return value


class JsonFormatter(logging.Formatter):
    """Render log records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": mask_text(record.getMessage()),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = mask_value(key, value)
        if record.exc_info:
            payload["exc"] = mask_text(self.formatException(record.exc_info))
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON formatter on the root logger (idempotent)."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
