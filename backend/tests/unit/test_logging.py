from __future__ import annotations

import json
import logging

from core.logging import JsonFormatter, mask_text, mask_value


def test_mask_inline_secrets() -> None:
    assert mask_text("password=hunter2 ok") == "password=*** ok"
    assert mask_text("api_key: abc123") == "api_key: ***"


def test_mask_url_credentials() -> None:
    masked = mask_text("postgresql+psycopg://gce:topsecret@db:5432/gce")
    assert "topsecret" not in masked
    assert "gce:***@db" in masked


def test_mask_structured_keys() -> None:
    assert mask_value("refresh_token", "abc") == "***"
    assert mask_value("payload", {"client_secret": "x", "n": 1}) == {"client_secret": "***", "n": 1}
    assert mask_value("views", 10) == 10


def test_json_formatter_emits_json_with_extras() -> None:
    record = logging.makeLogRecord(
        {"name": "t", "levelname": "INFO", "msg": "hello", "channel_id": 3, "token": "zzz"}
    )
    out = json.loads(JsonFormatter().format(record))
    assert out["msg"] == "hello"
    assert out["channel_id"] == 3
    assert out["token"] == "***"
    assert out["level"] == "INFO"
