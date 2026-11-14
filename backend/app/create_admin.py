"""CLI: create the first admin (or reset an admin password).

Usage: ``python -m app.create_admin --email admin@example.com``
The password is read from the ``GCE_ADMIN_PASSWORD`` environment variable or
prompted interactively; it is never accepted as a command-line argument.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

from sqlalchemy import select

from core.config import get_settings
from core.enums import UserRole
from core.security import WeakPasswordError, hash_password, validate_password_policy
from database.session import get_sessionmaker
from models.access import User
from services import audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create or reset an admin user")
    parser.add_argument("--email", required=True)
    args = parser.parse_args(argv)
    email = args.email.strip().lower()

    password = os.environ.get("GCE_ADMIN_PASSWORD") or getpass.getpass("Password: ")
    try:
        validate_password_policy(password, get_settings().password_min_length)
    except WeakPasswordError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    with get_sessionmaker()() as session, session.begin():
        user = session.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, password_hash=hash_password(password), role=UserRole.ADMIN)
            session.add(user)
            session.flush()
            action = "user.create_admin_cli"
        else:
            user.password_hash = hash_password(password)
            user.role = UserRole.ADMIN
            user.is_active = True
            user.session_version += 1
            action = "user.reset_admin_cli"
        audit.record(session, action, entity_type="users", entity_id=user.id, agent="cli")
    print(f"Admin ready: {email}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
