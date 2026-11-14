"""Encryption of stored credentials (OAuth tokens) with ``CREDENTIALS_ENCRYPTION_KEY``.

Fernet (AES-128-CBC + HMAC-SHA256). The key is derived from the configured secret
with SHA-256, so any sufficiently long random string works. Tokens are never
stored, logged or returned in plain text.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from core.config import Settings


class CredentialError(RuntimeError):
    """A stored credential cannot be decrypted (wrong or rotated key)."""


def _fernet(settings: Settings) -> Fernet:
    secret = settings.credentials_encryption_key.get_secret_value().encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret).digest()))


def encrypt(settings: Settings, plaintext: str) -> str:
    return _fernet(settings).encrypt(plaintext.encode()).decode()


def decrypt(settings: Settings, token: str) -> str:
    try:
        return _fernet(settings).decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise CredentialError("stored credential cannot be decrypted") from exc
