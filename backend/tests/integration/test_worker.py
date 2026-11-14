from __future__ import annotations

import pytest
from sqlalchemy.engine import Engine

from app import worker
from core.config import get_settings

pytestmark = pytest.mark.integration


def test_worker_refuses_to_start_during_emergency_stop(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EMERGENCY_STOP", "true")
    get_settings.cache_clear()
    try:
        assert worker.main() == 1
    finally:
        get_settings.cache_clear()
