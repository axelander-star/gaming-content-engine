"""Fixed cost items on the "Kosten" page (server, domain, subscriptions, …)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.deps import Admin, AppSettings, DbSession, Viewer, csrf_protect
from models.fixed_costs import FixedCost
from services import audit, fixed_costs

router = APIRouter(tags=["costs"], dependencies=[Depends(csrf_protect)])

Category = Literal["server", "domain", "subscription", "storage", "backup", "other"]


class FixedCostIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    provider: str | None = Field(default=None, max_length=80)
    category: Category = "other"
    amount: Decimal = Field(ge=0, le=100_000, decimal_places=2)
    currency: Literal["EUR", "USD"] = "EUR"
    interval: Literal["month", "year"] = "month"
    in_budget: bool = True
    is_active: bool = True
    note: str | None = Field(default=None, max_length=300)


class FixedCostPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    provider: str | None = Field(default=None, max_length=80)
    category: Category | None = None
    amount: Decimal | None = Field(default=None, ge=0, le=100_000, decimal_places=2)
    currency: Literal["EUR", "USD"] | None = None
    interval: Literal["month", "year"] | None = None
    in_budget: bool | None = None
    is_active: bool | None = None
    note: str | None = Field(default=None, max_length=300)


def _snapshot(item: FixedCost) -> dict[str, Any]:
    return {
        "name": item.name,
        "amount": str(item.amount),
        "currency": item.currency,
        "interval": item.interval,
        "in_budget": item.in_budget,
        "is_active": item.is_active,
    }


def _get(db: DbSession, item_id: int) -> FixedCost:
    item = db.get(FixedCost, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Fixed cost not found")
    return item


@router.get("/costs/fixed")
def list_fixed(_: Viewer, db: DbSession, settings: AppSettings) -> dict[str, Any]:
    t = fixed_costs.totals(db, settings)
    return {
        "items": t.items,
        "from_env": t.from_env,
        "monthly_eur": float(t.all_eur),
        "monthly_in_budget_eur": float(t.in_budget_eur),
    }


@router.post("/costs/fixed", status_code=201)
def add_fixed(
    body: FixedCostIn, admin: Admin, db: DbSession, settings: AppSettings
) -> dict[str, Any]:
    fixed_costs.seed_defaults(db, settings)  # keep the starting list when adding the first item
    item = FixedCost(**body.model_dump(), updated_by_user_id=admin.id)
    db.add(item)
    db.flush()
    audit.record(
        db,
        "fixed_cost.add",
        user_id=admin.id,
        entity_type="fixed_costs",
        entity_id=item.id,
        after=_snapshot(item),
    )
    db.commit()
    db.refresh(item)
    return fixed_costs.to_dict(item, settings)


@router.patch("/costs/fixed/{item_id}")
def update_fixed(
    item_id: int, body: FixedCostPatch, admin: Admin, db: DbSession, settings: AppSettings
) -> dict[str, Any]:
    item = _get(db, item_id)
    before = _snapshot(item)
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is None and key not in ("provider", "note"):
            continue
        setattr(item, key, value)
    item.updated_by_user_id = admin.id
    db.flush()
    audit.record(
        db,
        "fixed_cost.update",
        user_id=admin.id,
        entity_type="fixed_costs",
        entity_id=item.id,
        before=before,
        after=_snapshot(item),
    )
    db.commit()
    db.refresh(item)
    return fixed_costs.to_dict(item, settings)


@router.delete("/costs/fixed/{item_id}", status_code=204)
def delete_fixed(item_id: int, admin: Admin, db: DbSession) -> None:
    item = _get(db, item_id)
    audit.record(
        db,
        "fixed_cost.delete",
        user_id=admin.id,
        entity_type="fixed_costs",
        entity_id=item.id,
        before=_snapshot(item),
    )
    db.delete(item)
    db.commit()
