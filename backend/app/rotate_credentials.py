"""Re-encrypt all stored platform tokens with the current key.

Run with ``python -m app.rotate_credentials`` after moving the previous key to
``CREDENTIALS_ENCRYPTION_KEY_OLD``. Afterwards the old key can be removed.
Prints counts only, never a token.
"""

from __future__ import annotations

import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import crypto
from core.config import Settings, get_settings
from core.logging import configure_logging
from database.session import get_sessionmaker
from models.channels import ChannelCredential


def rotate_all(session: Session, settings: Settings) -> tuple[int, int]:
    """Returns (re-encrypted tokens, credentials that could not be decrypted)."""
    done, failed = 0, 0
    for cred in session.scalars(select(ChannelCredential)):
        try:
            if cred.access_token_enc:
                cred.access_token_enc = crypto.rotate(settings, cred.access_token_enc)
                done += 1
            if cred.refresh_token_enc:
                cred.refresh_token_enc = crypto.rotate(settings, cred.refresh_token_enc)
                done += 1
        except crypto.CredentialError:
            failed += 1
    return done, failed


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    with get_sessionmaker()() as session:
        done, failed = rotate_all(session, settings)
        if failed:
            session.rollback()
            print(
                f"{failed} Zugänge ließen sich mit keinem Schlüssel entschlüsseln; nichts geändert."
            )
            return 1
        session.commit()
    print(f"{done} Tokens mit dem neuen Schlüssel verschlüsselt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
