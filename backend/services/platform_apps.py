"""Platform app keys entered in the dashboard (27.11.2026).

Until now the TikTok and Instagram apps (key, secret, redirect URI) could only be
set as environment variables in the server's ``.env``, which needs SSH. The
operator can now enter them in the dashboard (System → "TikTok-App" / "Instagram-App"). They
are stored in ``system_settings`` under ``platform_app.<provider>``; the secret is
encrypted with :mod:`core.crypto` and never returned by the API.

Precedence: values saved in the dashboard win over the environment, field by
field; an empty dashboard field falls back to the environment variable.

:func:`apply` returns a copy of :class:`Settings` with the stored values filled in.
Every code path that needs the app keys calls it with its database session.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Any

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import crypto
from core.config import Settings
from models.access import SystemSetting
from services import audit

KEY_PREFIX = "platform_app."

#: provider → (settings field of the key, of the secret, of the redirect URI)
FIELDS: dict[str, tuple[str, str, str]] = {
    "tiktok": ("tiktok_client_key", "tiktok_client_secret", "tiktok_oauth_redirect_uri"),
    "instagram": ("instagram_app_id", "instagram_app_secret", "instagram_oauth_redirect_uri"),
}
CALLBACK_PATH = "/api/oauth/{provider}/callback"
MAX_LEN = 512


class PlatformAppError(ValueError):
    """Input refused; the message is shown to the operator."""


@dataclass(frozen=True)
class AppStatus:
    provider: str
    configured: bool
    source: str | None  # "studio", "env" or None
    client_key: str
    secret_set: bool
    redirect_uri: str
    redirect_uri_ok: bool


def _row(session: Session, provider: str) -> SystemSetting | None:
    return session.scalar(select(SystemSetting).where(SystemSetting.key == KEY_PREFIX + provider))


def _stored(session: Session, provider: str) -> dict[str, Any]:
    row = _row(session, provider)
    return dict(row.value) if row else {}


def _redirect_ok(uri: str) -> bool:
    """TikTok only accepts static absolute https URIs without query or fragment."""
    return uri.startswith("https://") and "?" not in uri and "#" not in uri


def apply(session: Session, settings: Settings) -> Settings:
    """``settings`` with the app keys saved in the dashboard filled in."""
    update: dict[str, Any] = {}
    for provider, (key_f, secret_f, redirect_f) in FIELDS.items():
        stored = _stored(session, provider)
        if stored.get("client_key"):
            update[key_f] = stored["client_key"]
        if stored.get("client_secret_enc"):
            # encryption key changed: fall back to the environment
            with contextlib.suppress(crypto.CredentialError):
                update[secret_f] = SecretStr(crypto.decrypt(settings, stored["client_secret_enc"]))
        if stored.get("redirect_uri"):
            update[redirect_f] = stored["redirect_uri"]
    return settings.model_copy(update=update) if update else settings


def status(session: Session, settings: Settings, provider: str) -> AppStatus:
    if provider not in FIELDS:
        raise PlatformAppError("Unbekannte Plattform")
    key_f, secret_f, redirect_f = FIELDS[provider]
    stored = _stored(session, provider)
    eff = apply(session, settings)
    key = str(getattr(eff, key_f) or "")
    secret = getattr(eff, secret_f).get_secret_value()
    redirect = str(getattr(eff, redirect_f) or "")
    if stored.get("client_key") or stored.get("client_secret_enc"):
        source: str | None = "studio"
    elif key or secret:
        source = "env"
    else:
        source = None
    return AppStatus(
        provider=provider,
        configured=bool(key and secret),
        source=source,
        client_key=key,
        secret_set=bool(secret),
        redirect_uri=redirect,
        redirect_uri_ok=_redirect_ok(redirect),
    )


def _clean(value: str | None, label: str) -> str:
    value = (value or "").strip()
    if len(value) > MAX_LEN:
        raise PlatformAppError(f"{label} ist zu lang")
    if any(c.isspace() for c in value):
        raise PlatformAppError(f"{label} darf keine Leerzeichen enthalten")
    return value


def save(
    session: Session,
    settings: Settings,
    provider: str,
    *,
    client_key: str,
    client_secret: str | None,
    redirect_uri: str,
    user_id: int | None,
) -> AppStatus:
    """Store the keys. ``client_secret`` None or empty keeps the saved secret."""
    if provider not in FIELDS:
        raise PlatformAppError("Unbekannte Plattform")
    key = _clean(client_key, "Client Key")
    secret = _clean(client_secret, "Client Secret")
    redirect = _clean(redirect_uri, "Weiterleitungs-URI")
    if not key:
        raise PlatformAppError("Client Key fehlt")
    if redirect and not _redirect_ok(redirect):
        raise PlatformAppError(
            "Weiterleitungs-URI muss mit https:// beginnen und darf kein ? oder # enthalten"
        )
    if not settings.credentials_encryption_key.get_secret_value():
        raise PlatformAppError(
            "Auf dem Server fehlt CREDENTIALS_ENCRYPTION_KEY, ohne ihn kann nichts sicher "
            "gespeichert werden"
        )
    row = _row(session, provider)
    old = dict(row.value) if row else {}
    env_secret = getattr(settings, FIELDS[provider][1]).get_secret_value()
    if not secret and not old.get("client_secret_enc") and not env_secret:
        raise PlatformAppError("Client Secret fehlt")
    value: dict[str, Any] = {"client_key": key, "redirect_uri": redirect}
    if secret:
        value["client_secret_enc"] = crypto.encrypt(settings, secret)
    elif old.get("client_secret_enc"):
        value["client_secret_enc"] = old["client_secret_enc"]
    if row is None:
        session.add(
            SystemSetting(
                key=KEY_PREFIX + provider,
                value=value,
                description=f"{provider} app keys (secret encrypted)",
                updated_by_user_id=user_id,
            )
        )
    else:
        row.value = value
        row.updated_by_user_id = user_id
    audit.record(
        session,
        "settings.platform_app.update",
        user_id=user_id,
        entity_type="system_settings",
        before={
            "provider": provider,
            "client_key": old.get("client_key"),
            "redirect_uri": old.get("redirect_uri"),
        },
        after={
            "provider": provider,
            "client_key": key,
            "redirect_uri": redirect,
            "secret_changed": bool(secret),
        },
    )
    session.flush()
    return status(session, settings, provider)


def clear(session: Session, settings: Settings, provider: str, user_id: int | None) -> AppStatus:
    """Remove the keys saved in the dashboard; the environment applies again."""
    if provider not in FIELDS:
        raise PlatformAppError("Unbekannte Plattform")
    row = _row(session, provider)
    if row is not None:
        session.delete(row)
        audit.record(
            session,
            "settings.platform_app.clear",
            user_id=user_id,
            entity_type="system_settings",
            before={"provider": provider},
        )
        session.flush()
    return status(session, settings, provider)
