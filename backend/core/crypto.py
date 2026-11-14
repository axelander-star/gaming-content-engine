"""Encryption of stored credentials (OAuth tokens) with ``CREDENTIALS_ENCRYPTION_KEY``.

Fernet (AES-128-CBC + HMAC-SHA256). The key is derived from the configured secret
with SHA-256, so any sufficiently long random string works. Tokens are never
stored, logged or returned in plain text.

Key rotation (Phase 15): put the new key into ``CREDENTIALS_ENCRYPTION_KEY`` and
the previous one(s) into ``CREDENTIALS_ENCRYPTION_KEY_OLD`` (comma-separated).
Decryption tries every key, encryption always uses the new one, and
:func:`rotate` re-encrypts the stored tokens so the old keys can be removed.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from core.config import Settings


class CredentialError(RuntimeError):
    """A stored credential cannot be decrypted (wrong or rotated key)."""


def _key(secret: str) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def _fernet(settings: Settings) -> MultiFernet:
    keys = [settings.credentials_encryption_key.get_secret_value()]
    keys += [
        k.strip() for k in settings.credentials_encryption_key_old.get_secret_value().split(",")
    ]
    return MultiFernet([_key(k) for k in keys if k])


def encrypt(settings: Settings, plaintext: str) -> str:
    return _fernet(settings).encrypt(plaintext.encode()).decode()


def decrypt(settings: Settings, token: str) -> str:
    try:
        return _fernet(settings).decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise CredentialError("stored credential cannot be decrypted") from exc


def rotate(settings: Settings, token: str) -> str:
    """Re-encrypt ``token`` with the current key (no-op content-wise)."""
    try:
        return _fernet(settings).rotate(token.encode()).decode()
    except InvalidToken as exc:
        raise CredentialError("stored credential cannot be decrypted") from exc
