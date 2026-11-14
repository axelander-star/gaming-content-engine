"""Shared fixtures.

Integration tests need PostgreSQL and Redis. Configure them via
``TEST_DATABASE_URL`` and ``REDIS_HOST/REDIS_PORT/REDIS_PASSWORD``; tests marked
``integration`` are skipped automatically if the services are unreachable.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("APP_ENV", "test")
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://gce@127.0.0.1:5432/gce_test"
)
os.environ.setdefault("REDIS_HOST", "127.0.0.1")
os.environ.setdefault("REDIS_DB", "15")  # keep tests away from dev data

from alembic import command
from alembic.config import Config
from redis import Redis
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from core.config import get_settings
from services.queue import get_redis

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    eng = create_engine(get_settings().database_url)
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip("PostgreSQL not reachable")
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "database/migrations"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    """Session inside a transaction that is rolled back after each test."""
    conn = engine.connect()
    trans = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        conn.close()


@pytest.fixture
def redis_client() -> Iterator[Redis]:
    client = get_redis()
    try:
        client.ping()
    except Exception:
        pytest.skip("Redis not reachable")
    client.flushdb()
    yield client
    client.flushdb()
