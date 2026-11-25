"""Forwarding addresses for new platform accounts via Cloudflare Email Routing.

Each TikTok or Instagram account needs its own e-mail address. Instead of real
mailboxes the engine creates forwarding rules on the operator's own domain
(e.g. ``uhren-de-tiktok@kanalfabrik.de``) that deliver to one verified inbox.
Cloudflare Email Routing is free and has an API.

Endpoints (Cloudflare API v4, "Email Routing > Routing Rules"):

* ``POST   /zones/{zone_id}/email/routing/rules``          create a rule
* ``DELETE /zones/{zone_id}/email/routing/rules/{rule_id}`` delete a rule
* ``GET    /zones/{zone_id}/email/routing/rules``          list rules (paged)
* ``GET    /zones/{zone_id}/email/routing``                Email Routing settings

Creating is idempotent: an existing rule for the same address is reused, so a
retry after a timeout never leaves two rules. Cloudflare allows at most 200
routing rules per domain; :func:`check` warns before that limit is reached.

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
#: Cloudflare limit "routing rules per domain" (Email Service platform limits).
RULE_LIMIT = 200
RULE_WARN = 180
_PER_PAGE = 50
_MAX_PAGES = 10
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


def _rules(settings: Settings, http: httpx.Client) -> list[dict[str, object]]:
    """All routing rules of the zone (raises ``RuntimeError`` with Cloudflare's message)."""
    rules: list[dict[str, object]] = []
    for page in range(1, _MAX_PAGES + 1):
        res = http.get(
            f"/zones/{settings.cloudflare_zone_id}/email/routing/rules",
            params={"page": page, "per_page": _PER_PAGE},
            headers=_auth(settings),
        )
        data = res.json() if res.content else {}
        if res.status_code >= 400 or not data.get("success"):
            raise RuntimeError(_errors(data, res.status_code))
        batch = data.get("result") or []
        rules.extend(r for r in batch if isinstance(r, dict))
        if len(batch) < _PER_PAGE:
            break
    return rules


def _errors(data: dict[str, object], status: int) -> str:
    errors = data.get("errors") or [{"message": f"HTTP {status}"}]
    items = errors if isinstance(errors, list) else [errors]
    return "; ".join(str(e.get("message", e)) if isinstance(e, dict) else str(e) for e in items)[
        :500
    ]


def _rule_for(rules: list[dict[str, object]], address: str) -> dict[str, object] | None:
    for rule in rules:
        matchers = rule.get("matchers") or []
        for m in matchers if isinstance(matchers, list) else []:
            if (
                isinstance(m, dict)
                and m.get("type") == "literal"
                and str(m.get("value", "")).lower() == address
            ):
                return rule
    return None


@dataclass(frozen=True)
class RoutingCheck:
    """Result of :func:`check`; ``ok`` means new addresses will really receive mail."""

    ok: bool
    mode: str
    enabled: bool | None = None
    status: str | None = None
    rules_used: int | None = None
    rule_limit: int = RULE_LIMIT
    findings: tuple[str, ...] = ()


def check(settings: Settings, client: httpx.Client | None = None) -> RoutingCheck:
    """Ask Cloudflare whether Email Routing is active and how many rules are left.

    Reads only; never changes anything. Findings are German sentences for the
    dashboard. The destination address cannot be checked with a zone token
    (that needs an account permission), so the test mail covers it."""
    if settings.mail_routing_mode != "live":
        return RoutingCheck(
            ok=False,
            mode="mock",
            findings=(
                "Testmodus (MAIL_ROUTING_MODE=mock): Es wird nichts bei Cloudflare angelegt. "
                "Adressen aus dem Testmodus empfangen keine Mails.",
            ),
        )
    problem = live_problem(settings)
    if problem:
        return RoutingCheck(ok=False, mode="live", findings=(problem,))
    findings: list[str] = []
    enabled: bool | None = None
    status: str | None = None
    used: int | None = None
    own = client is None
    http = client or _client(settings)
    try:
        res = http.get(
            f"/zones/{settings.cloudflare_zone_id}/email/routing", headers=_auth(settings)
        )
        data = res.json() if res.content else {}
        if res.status_code >= 400 or not data.get("success"):
            findings.append(
                "Status von Email Routing nicht lesbar ("
                + _errors(data, res.status_code)
                + "). Bitte im Cloudflare-Dashboard unter E-Mail > E-Mail-Routing prüfen, "
                "ob es aktiviert ist."
            )
        else:
            result = data.get("result") or {}
            enabled = bool(result.get("enabled"))
            status = str(result.get("status") or "") or None
            if not enabled:
                findings.append(
                    "Email Routing ist für die Domain nicht aktiviert. Im Cloudflare-Dashboard "
                    "unter E-Mail > E-Mail-Routing einschalten und die MX-Einträge übernehmen."
                )
            elif status and status != "ready":
                findings.append(
                    f"Email Routing meldet den Status „{status}“. Meist fehlen MX- oder "
                    "SPF-Einträge; Cloudflare zeigt unter E-Mail-Routing, was fehlt."
                )
        try:
            used = len(_rules(settings, http))
        except RuntimeError as exc:
            findings.append(f"Regeln nicht lesbar: {exc}. Hat das Token das Recht auf die Zone?")
        if used is not None and used >= RULE_LIMIT:
            findings.append(
                f"Alle {RULE_LIMIT} Weiterleitungsregeln sind belegt. Erledigte oder "
                "verworfene Adressen löschen oder eine zweite Domain nutzen."
            )
        elif used is not None and used >= RULE_WARN:
            findings.append(
                f"{used} von {RULE_LIMIT} Weiterleitungsregeln belegt, "
                "bald ist die Grenze erreicht."
            )
    except (httpx.HTTPError, ValueError):
        findings.append("Cloudflare nicht erreichbar, bitte später erneut prüfen.")
    finally:
        if own:
            http.close()
    ok = enabled is True and (status in (None, "ready")) and used is not None and used < RULE_LIMIT
    return RoutingCheck(
        ok=ok,
        mode="live",
        enabled=enabled,
        status=status,
        rules_used=used,
        findings=tuple(findings),
    )


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
        try:
            existing = _rule_for(_rules(settings, http), address)
        except RuntimeError:
            existing = None  # listing not allowed: creating may still work
        if existing is not None:
            rule_id = str(existing.get("id") or existing.get("tag") or "") or None
            return AliasResult(address, MailAliasStatus.CREATED, rule_id=rule_id)
        res = http.post(
            f"/zones/{settings.cloudflare_zone_id}/email/routing/rules",
            json=body,
            headers=_auth(settings),
        )
        data = res.json() if res.content else {}
        if res.status_code >= 400 or not data.get("success"):
            msg = _errors(data, res.status_code)
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
