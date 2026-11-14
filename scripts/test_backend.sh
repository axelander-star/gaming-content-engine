#!/usr/bin/env bash
# Runs lint, type check and tests for the backend.
# Needs PostgreSQL and Redis, e.g. started via: docker compose up -d postgres redis
#   TEST_DATABASE_URL  (default postgresql+psycopg://gce@127.0.0.1:5432/gce_test)
#   REDIS_PASSWORD     (password of the local Redis, if set)
set -euo pipefail
cd "$(dirname "$0")/../backend"
ruff check .
ruff format --check .
mypy .
pytest --cov=. --cov-report=term-missing "$@"
