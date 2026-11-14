"""Shared fixtures.

Integration tests need PostgreSQL and Redis. Configure them via
``TEST_DATABASE_URL`` and ``REDIS_HOST/REDIS_PORT/REDIS_PASSWORD``; tests marked
``integration`` are skipped automatically if the services are unreachable.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator

import pytest

os.environ.setdefault("APP_ENV", "test")
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://gce@127.0.0.1:5432/gce_test"
)
os.environ.setdefault("REDIS_HOST", "127.0.0.1")
os.environ.setdefault("REDIS_DB", "15")  # keep tests away from dev data
os.environ.setdefault("SESSION_COOKIE_SECURE", "false")  # TestClient talks plain HTTP
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-0123456789")

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from core.config import get_settings
from core.enums import UserRole
from models.access import User
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


# --- API fixtures -----------------------------------------------------------

STRONG_PASSWORD = "Sicher-Passwort-2026"


@pytest.fixture
def api(db: Session, redis_client: Redis) -> Iterator[TestClient]:
    """TestClient whose requests share the rolled-back test session and test Redis."""
    from app.main import create_app
    from database.session import get_db

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_redis] = lambda: redis_client
    with TestClient(app) as client:
        yield client


@pytest.fixture
def make_user(db: Session) -> Callable[..., User]:
    from core.security import hash_password

    def _make(
        email: str = "admin@example.com",
        role: UserRole = UserRole.ADMIN,
        password: str = STRONG_PASSWORD,
        is_active: bool = True,
    ) -> User:
        user = User(
            email=email, password_hash=hash_password(password), role=role, is_active=is_active
        )
        db.add(user)
        db.flush()
        return user

    return _make


def login(client: TestClient, email: str, password: str = STRONG_PASSWORD) -> dict[str, str]:
    """Log in and return headers carrying the CSRF token for unsafe requests."""
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": client.cookies["gce_csrf"]}
