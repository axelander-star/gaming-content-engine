"""CLI: create base data. Run with ``python -m app.seed`` (idempotent)."""

from __future__ import annotations

import json
import sys

from core.config import get_settings
from core.logging import configure_logging
from database.session import get_sessionmaker
from services.fixed_costs import seed_defaults
from services.seed import seed_base_data


def main() -> int:
    configure_logging(get_settings().log_level)
    with get_sessionmaker()() as session, session.begin():
        created = seed_base_data(session)
        created["fixed_costs"] = seed_defaults(session, get_settings())
    print(json.dumps({"created": created}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
