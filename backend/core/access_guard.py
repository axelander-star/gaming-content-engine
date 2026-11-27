"""Cloudflare Access check for a privately operated instance.

Cloudflare Access sits in front of the whole domain and only lets the operator
through. Requests that arrive through the Access application carry a signed JWT
in the ``Cf-Access-Jwt-Assertion`` header (and the ``CF_Authorization`` cookie).
This module verifies that token inside the backend as a second line of defence:
if someone reaches the server without passing Access (misconfigured tunnel,
open port, bypass rule), the API still answers 403.

Checks: RS256 signature against the team's public keys
(``https://<team>/cdn-cgi/access/certs``), audience (AUD tag of the application),
issuer, expiry and, optionally, an e-mail allow list.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import jwt

from core.config import Settings

HEADER = "Cf-Access-Jwt-Assertion"
COOKIE = "CF_Authorization"
#: Paths reachable without the Access token: container health checks and Uptime Kuma
#: call the backend directly inside the Docker network, not through Cloudflare.
#: Public bio-link pages (A8) have their own host without Cloudflare Access.
#: The GitHub webhook (instant server update) has its own host as well and is
#: authenticated by its HMAC signature instead.
EXEMPT_PREFIXES = ("/api/health", "/api/public", "/api/hooks")
#: Tolerated clock difference between Cloudflare and the server.
LEEWAY_S = 30


class AccessDeniedError(Exception):
    """The request did not pass the Cloudflare Access check."""


def team_url(settings: Settings) -> str:
    domain = settings.cf_access_team_domain.strip().removeprefix("https://").rstrip("/")
    return f"https://{domain}"


@lru_cache(maxsize=4)
def _jwks_client(certs_url: str) -> jwt.PyJWKClient:
    # Keys are cached; Cloudflare rotates them regularly and the client refetches
    # when an unknown key id shows up.
    return jwt.PyJWKClient(certs_url, cache_keys=True, lifespan=3600, timeout=10)


def signing_key(settings: Settings, token: str) -> Any:
    """Public key for ``token`` from the team's certificate endpoint."""
    client = _jwks_client(f"{team_url(settings)}/cdn-cgi/access/certs")
    return client.get_signing_key_from_jwt(token).key


def is_exempt(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in EXEMPT_PREFIXES)


def verify(settings: Settings, token: str | None) -> dict[str, Any]:
    """Return the token claims or raise :class:`AccessDeniedError`."""
    if not token:
        raise AccessDeniedError("missing Cloudflare Access token")
    try:
        key = signing_key(settings, token)
        claims: dict[str, Any] = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=settings.cf_access_aud.strip(),
            issuer=team_url(settings),
            options={"require": ["exp", "iat", "aud", "iss"]},
            leeway=LEEWAY_S,
        )
    except (jwt.PyJWTError, OSError) as exc:
        raise AccessDeniedError(f"invalid Cloudflare Access token: {type(exc).__name__}") from exc
    allowed = settings.cf_access_emails
    if allowed:
        email = str(claims.get("email", "")).lower()
        if email not in allowed:
            raise AccessDeniedError("e-mail address not on the allow list")
    return claims
