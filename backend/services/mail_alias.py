"""Forwarding addresses for new platform accounts via Cloudflare Email Routing.

Each TikTok or Instagram account needs its own e-mail address. Instead of real
mailboxes the engine creates forwarding rules on the operator's own domain
(e.g. ``uhren-de-tiktok@kanalfabrik.de``) that deliver to one verified inbox.
Cloudflare Email Routing is free and has an API.

Endpoints (Cloudflare API v4, "Email Routing > Routing Rules"):

* ``POST   /zones/{zone_id}/email/routing/rules``          create a rule
* ``DELETE /zones/{zone_id}/email/routing/rules/{rule_id}`` delete a rule

The destination address must already be verified in the Cloudflare account
(one click in the confirmation mail); the API cannot do that for us. The token
needs only "Zone > Email Routing Rules > Edit" on this one zone.

``MAIL_ROUTING_MODE=mock`` (default) never calls Cloudflare: the address is only
proposed and the operator sees that it is not created yet.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

from core.config import Settings
from core.enums import MailAliasStatus

log = logging.getLogger(__name__)

API = "https://api.cloudflare.com/client/v4"
_LOCAL_PART = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")


@dataclass(frozen=True)
class AliasResult:
    address: str | None
    status: MailAliasStatus
    rule_id: str | None = None
    error: str | None = None


def local_part(*parts: str) -> str:
    """``("Uhren & Mode", "de", "tiktok")`` -> ``uhren-mode-de-tiktok`` (max 64 chars)."""
    from services.projects import slugify

    text = "-".join(slugify(p) for p in parts if p)
    text = re.sub(r"-{2,}", "-", text).strip("-")[:64].strip("-")
    return text or "kanal"


def address_for(settings: Settings, local: str) -> str | None:
    domain = settings.mail_alias_domain.strip().lower()
    if not domain or not _LOCAL_PART.match(local):
        return None
    return f"{local}@{domain}"


def live_problem(settings: Settings) -> str | None:
    """Why live mode cannot create addresses (German, shown in the dashboard)."""
    missing = [
        name
        for name, value in (
            ("MAIL_ALIAS_DOMAIN", settings.mail_alias_domain),
            ("MAIL_FORWARD_TO", settings.mail_forward_to),
            ("CLOUDFLARE_ZONE_ID", settings.cloudflare_zone_id),
            ("CLOUDFLARE_API_TOKEN", settings.cloudflare_api_token.get_secret_value()),
        )
        if not value.strip()
    ]
    if missing:
        return "Es fehlen Einstellungen: " + ", ".join(missing)
    return None


def _client(settings: Settings) -> httpx.Client:
    return httpx.Client(base_url=API, timeout=settings.http_timeout_s)


def _auth(settings: Settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.cloudflare_api_token.get_secret_value()}"}


def create(
    settings: Settings, local: str, label: str, client: httpx.Client | None = None
) -> AliasResult:
    """Create the forwarding rule for ``local``@domain (or only propose it in mock mode)."""
    address = address_for(settings, local)
    if address is None:
        return AliasResult(
            None,
            MailAliasStatus.MOCK,
            error="MAIL_ALIAS_DOMAIN ist nicht gesetzt, darum gibt es noch keine Adresse.",
        )
    if settings.mail_routing_mode != "live":
        return AliasResult(address, MailAliasStatus.MOCK)
    problem = live_problem(settings)
    if problem:
        return AliasResult(address, MailAliasStatus.FAILED, error=problem)
    body = {
        "name": f"Kanal-Assistent: {label}"[:200],
        "enabled": True,
        "matchers": [{"type": "literal", "field": "to", "value": address}],
        "actions": [{"type": "forward", "value": [settings.mail_forward_to.strip()]}],
    }
    own = client is None
    http = client or _client(settings)
    try:
        res = http.post(
            f"/zones/{settings.cloudflare_zone_id}/email/routing/rules",
            json=body,
            headers=_auth(settings),
        )
        data = res.json() if res.content else {}
        if res.status_code >= 400 or not data.get("success"):
            errors = data.get("errors") or [{"message": f"HTTP {res.status_code}"}]
            msg = "; ".join(str(e.get("message", e)) for e in errors)[:500]
            log.warning("mail alias %s not created: %s", address, msg)
            return AliasResult(address, MailAliasStatus.FAILED, error=f"Cloudflare: {msg}")
        result = data.get("result") or {}
        rule_id = str(result.get("id") or result.get("tag") or "") or None
        return AliasResult(address, MailAliasStatus.CREATED, rule_id=rule_id)
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("mail alias %s not created: %s", address, type(exc).__name__)
        return AliasResult(
            address,
            MailAliasStatus.FAILED,
            error="Cloudflare nicht erreichbar, bitte erneut versuchen.",
        )
    finally:
        if own:
            http.close()


def delete(settings: Settings, rule_id: str, client: httpx.Client | None = None) -> bool:
    """Remove a rule again (task dismissed). Mock mode and missing config do nothing."""
    if settings.mail_routing_mode != "live" or live_problem(settings) or not rule_id:
        return False
    own = client is None
    http = client or _client(settings)
    try:
        res = http.delete(
            f"/zones/{settings.cloudflare_zone_id}/email/routing/rules/{rule_id}",
            headers=_auth(settings),
        )
        return res.status_code < 400
    except httpx.HTTPError:
        return False
    finally:
        if own:
            http.close()
