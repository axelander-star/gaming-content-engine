"""Recurring fixed costs (server, domain, subscriptions) entered in the dashboard.

Each item has its own currency and interval; this module converts everything
to euro per month. Items with ``in_budget`` count against the engine budget,
the others (e.g. a personal Claude Pro plan) only show up in the totals.

As long as no item was ever stored, the old environment values
``SERVER_MONTHLY_EUR`` / ``OTHER_FIXED_MONTHLY_EUR`` act as fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from models.access import SystemSetting
from models.fixed_costs import FixedCost

SEEDED_KEY = "fixed_costs.seeded"
_CENT = Decimal("0.0001")

#: Starting list for the operator's real setup (operator message 22.11.2026).
#: Amounts of 0 mean "price still to be entered" and are flagged in the dashboard.
DEFAULTS: tuple[dict[str, Any], ...] = (
    {
        "name": "Server Cloud VPS 8",
        "provider": "Contabo",
        "category": "server",
        "amount": Decimal("13.33"),
        "currency": "EUR",
        "interval": "month",
        "in_budget": True,
        "note": "8 Kerne, 24 GB RAM, 300 GB SSD",
    },
    {
        "name": "Domain kanalfabrik.de",
        "provider": "INWX",
        "category": "domain",
        "amount": Decimal("0"),
        "currency": "EUR",
        "interval": "year",
        "in_budget": True,
        "note": "Jahrespreis laut INWX-Rechnung eintragen",
    },
    {
        "name": "Claude Pro (Chat-Abo)",
        "provider": "Anthropic",
        "category": "subscription",
        "amount": Decimal("20.00"),
        "currency": "USD",
        "interval": "month",
        "in_budget": False,
        "note": "Persönliches Abo; enthält keinen API-Zugang für die Engine",
    },
    {
        "name": "Cloudflare (DNS, Tunnel, Access)",
        "provider": "Cloudflare",
        "category": "other",
        "amount": Decimal("0"),
        "currency": "EUR",
        "interval": "month",
        "in_budget": True,
        "note": "Free-Tarif",
    },
    {
        "name": "Cloudflare R2 Speicher",
        "provider": "Cloudflare",
        "category": "storage",
        "amount": Decimal("0"),
        "currency": "EUR",
        "interval": "month",
        "in_budget": True,
        "note": "Bis 10 GB frei; darüber Preis eintragen",
    },
)


@dataclass(frozen=True)
class FixedTotals:
    in_budget_eur: Decimal
    all_eur: Decimal
    items: list[dict[str, Any]]
    from_env: bool


def monthly_eur(item: FixedCost, settings: Settings) -> Decimal:
    amount = Decimal(item.amount)
    if item.currency == "USD":
        amount *= Decimal(str(settings.eur_per_usd))
    if item.interval == "year":
        amount /= 12
    return amount.quantize(_CENT, rounding=ROUND_HALF_UP)


def _has_items(session: Session) -> bool:
    if session.scalar(select(FixedCost.id).limit(1)) is not None:
        return True
    return (
        session.scalar(select(SystemSetting.id).where(SystemSetting.key == SEEDED_KEY)) is not None
    )


def totals(session: Session, settings: Settings) -> FixedTotals:
    if not _has_items(session):
        env = Decimal(str(settings.server_monthly_eur)) + Decimal(
            str(settings.other_fixed_monthly_eur)
        )
        return FixedTotals(env, env, [], True)
    rows = session.scalars(select(FixedCost).order_by(FixedCost.id)).all()
    items = [to_dict(r, settings) for r in rows]
    active = [(r, monthly_eur(r, settings)) for r in rows if r.is_active]
    return FixedTotals(
        in_budget_eur=sum((m for r, m in active if r.in_budget), Decimal(0)),
        all_eur=sum((m for _r, m in active), Decimal(0)),
        items=items,
        from_env=False,
    )


def to_dict(item: FixedCost, settings: Settings) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "provider": item.provider,
        "category": item.category,
        "amount": float(item.amount),
        "currency": item.currency,
        "interval": item.interval,
        "in_budget": item.in_budget,
        "is_active": item.is_active,
        "note": item.note,
        "monthly_eur": float(monthly_eur(item, settings)),
        "missing_price": Decimal(item.amount) == 0 and item.category in ("server", "domain"),
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def seed_defaults(session: Session, settings: Settings) -> int:
    """Create the starting list once; later deletions by the operator stay deleted."""
    if _has_items(session):
        return 0
    rows = [dict(d) for d in DEFAULTS]
    if settings.server_monthly_eur > 0:  # value the operator already set in .env
        rows[0]["amount"] = Decimal(str(settings.server_monthly_eur))
    if settings.other_fixed_monthly_eur > 0:
        rows.append(
            {
                "name": "Weitere Fixkosten (aus .env übernommen)",
                "provider": None,
                "category": "other",
                "amount": Decimal(str(settings.other_fixed_monthly_eur)),
                "currency": "EUR",
                "interval": "month",
                "in_budget": True,
                "note": "OTHER_FIXED_MONTHLY_EUR; bitte aufteilen",
            }
        )
    session.add_all(FixedCost(**r) for r in rows)
    session.add(
        SystemSetting(
            key=SEEDED_KEY,
            value={"seeded": True},
            description="Startliste der Fixkosten wurde angelegt",
        )
    )
    session.flush()
    return len(rows)


def accrued(monthly: Decimal, month_start: datetime, now: datetime) -> Decimal:
    """Share of a monthly amount that has accrued from month start until ``now``."""
    if month_start.month == 12:
        nxt = month_start.replace(year=month_start.year + 1, month=1)
    else:
        nxt = month_start.replace(month=month_start.month + 1)
    share = Decimal(str((now - month_start).total_seconds() / (nxt - month_start).total_seconds()))
    return (monthly * min(Decimal(1), max(Decimal(0), share))).quantize(_CENT)
