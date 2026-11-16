"""Account overview (A2): all channels with reach, revenue and recommendation; revenue entries."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from api.deps import Admin, AppSettings, DbSession, Viewer, csrf_protect
from core.enums import ChannelAuthStatus, PlatformCode, RevenueSource
from models.channels import Channel
from models.revenue import RevenueEntry
from services import accounts, audit

router = APIRouter(prefix="/accounts", tags=["accounts"], dependencies=[Depends(csrf_protect)])


class AccountOut(BaseModel):
    channel_id: int
    name: str
    platform: PlatformCode
    language: str
    project_id: int
    project: str
    auth_status: ChannelAuthStatus
    is_paused: bool
    handle: str | None
    first_post_at: datetime | None
    last_post_at: datetime | None
    total_posts: int
    posts_30d: int
    views_30d: int
    views_prev_30d: int
    followers_30d: int
    engagement_30d: float | None
    trend_30d: float | None
    views_per_post: float | None
    revenue_30d: Decimal
    revenue_review: Decimal
    revenue_by_source: dict[str, Decimal]
    estimate_30d: Decimal
    status: str
    status_label: str
    reasons: list[str]


class ProjectSummary(BaseModel):
    project_id: int
    project: str
    channels: int
    views_30d: int
    revenue_30d: Decimal
    estimate_30d: Decimal


class SummaryOut(BaseModel):
    channels: int
    connected: int
    views_30d: int
    views_prev_30d: int
    followers_30d: int
    revenue_30d: Decimal
    estimate_30d: Decimal
    by_status: dict[str, int]
    projects: list[ProjectSummary]
    top_revenue: list[int]
    review_days: int


class OverviewOut(BaseModel):
    summary: SummaryOut
    accounts: list[AccountOut]


class RevenueIn(BaseModel):
    channel_id: int
    source: RevenueSource
    amount_eur: Decimal = Field(ge=0, le=Decimal("1000000"), decimal_places=2)
    period_start: date
    period_end: date
    note: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _order(self) -> RevenueIn:
        if self.period_end < self.period_start:
            raise ValueError("period_end must not be before period_start")
        return self


class RevenueOut(BaseModel):
    id: int
    channel_id: int
    source: RevenueSource
    amount_eur: Decimal
    period_start: date
    period_end: date
    note: str | None
    created_at: datetime


def _rev_out(e: RevenueEntry) -> RevenueOut:
    return RevenueOut(
        id=e.id,
        channel_id=e.channel_id,
        source=e.source,
        amount_eur=e.amount_eur,
        period_start=e.period_start,
        period_end=e.period_end,
        note=e.note,
        created_at=e.created_at,
    )


@router.get("", response_model=OverviewOut)
def overview(_: Viewer, db: DbSession, settings: AppSettings) -> OverviewOut:
    rows = accounts.overview(db, settings)
    s = accounts.summary(rows)
    return OverviewOut(
        summary=SummaryOut(**s, review_days=settings.account_review_days),
        accounts=[AccountOut(**a.as_dict()) for a in rows],
    )


@router.get("/revenue", response_model=list[RevenueOut])
def list_revenue(_: Viewer, db: DbSession, channel_id: int | None = None) -> list[RevenueOut]:
    q = select(RevenueEntry).order_by(RevenueEntry.period_end.desc(), RevenueEntry.id.desc())
    if channel_id is not None:
        q = q.where(RevenueEntry.channel_id == channel_id)
    return [_rev_out(e) for e in db.scalars(q.limit(500))]


@router.post("/revenue", response_model=RevenueOut, status_code=201)
def add_revenue(body: RevenueIn, admin: Admin, db: DbSession) -> RevenueOut:
    if db.get(Channel, body.channel_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Kanal nicht gefunden")
    entry = RevenueEntry(**body.model_dump(), created_by_user_id=admin.id)
    db.add(entry)
    db.flush()
    audit.record(
        db,
        "revenue.add",
        user_id=admin.id,
        entity_type="revenue_entries",
        entity_id=entry.id,
        after=body.model_dump(mode="json"),
    )
    db.commit()
    return _rev_out(entry)


@router.delete("/revenue/{entry_id}", status_code=204)
def delete_revenue(entry_id: int, admin: Admin, db: DbSession) -> None:
    entry = db.get(RevenueEntry, entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Eintrag nicht gefunden")
    before = {"channel_id": entry.channel_id, "amount_eur": str(entry.amount_eur)}
    db.delete(entry)
    audit.record(
        db,
        "revenue.delete",
        user_id=admin.id,
        entity_type="revenue_entries",
        entity_id=entry_id,
        before=before,
    )
    db.commit()
