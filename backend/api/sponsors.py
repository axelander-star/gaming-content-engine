"""Sponsor inbox (Ausbau A9): inquiries, price suggestion and reply drafts; nothing is sent."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from api.deps import AppSettings, DbSession, Operator, csrf_protect
from models.projects import ContentProject
from models.sponsors import SponsorInquiry
from services import audit, sponsors

router = APIRouter(prefix="/sponsors", tags=["sponsors"], dependencies=[Depends(csrf_protect)])


class InquiryIn(BaseModel):
    sender: str = Field(default="", max_length=400)
    subject: str | None = Field(default=None, max_length=300)
    body: str = Field(min_length=1, max_length=20000)
    project_id: int | None = None


class InquiryPatch(BaseModel):
    status: str | None = None
    project_id: int | None = None
    draft: str | None = Field(default=None, max_length=5000)
    price_eur: Decimal | None = Field(default=None, ge=0, le=1_000_000)
    note: str | None = Field(default=None, max_length=2000)


class InquiryOut(BaseModel):
    id: int
    project_id: int | None
    project: str | None
    brand: str
    contact_email: str | None
    subject: str | None
    body: str
    received_at: datetime
    language: str
    category: str
    category_label: str
    status: str
    flags: list[str]
    fit_score: int
    price_eur: float | None
    price_basis: dict[str, Any]
    draft: str
    draft_source: str
    note: str | None


class InboxOut(BaseModel):
    counts: dict[str, int]
    inquiries: list[InquiryOut]


def _out(db: DbSession, inq: SponsorInquiry) -> InquiryOut:
    project = db.get(ContentProject, inq.content_project_id) if inq.content_project_id else None
    return InquiryOut(
        id=inq.id, project_id=inq.content_project_id, project=project.name if project else None,
        brand=inq.brand, contact_email=inq.contact_email, subject=inq.subject, body=inq.body,
        received_at=inq.received_at, language=inq.language.value, category=inq.category,
        category_label=sponsors.CATEGORY_LABELS.get(inq.category, inq.category),
        status=inq.status, flags=[str(f) for f in inq.flags or []], fit_score=inq.fit_score,
        price_eur=float(inq.price_eur) if inq.price_eur is not None else None,
        price_basis=inq.price_basis or {}, draft=inq.draft, draft_source=inq.draft_source,
        note=inq.note,
    )  # fmt: skip


def _get(db: DbSession, inquiry_id: int) -> SponsorInquiry:
    inq = db.get(SponsorInquiry, inquiry_id)
    if inq is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Anfrage nicht gefunden")
    return inq


@router.get("", response_model=InboxOut)
def inbox(
    _: Operator, db: DbSession, state: str | None = Query(default=None, max_length=16)
) -> InboxOut:
    """Operators only: inquiries hold names and addresses of business contacts."""
    counts = dict(
        db.execute(
            select(SponsorInquiry.status, func.count(SponsorInquiry.id)).group_by(
                SponsorInquiry.status
            )
        ).all()
    )
    q = select(SponsorInquiry).order_by(SponsorInquiry.received_at.desc()).limit(200)
    if state:
        q = q.where(SponsorInquiry.status == state)
    else:
        q = q.where(SponsorInquiry.status.in_(("new", "replied", "won")))
    return InboxOut(
        counts={s: int(counts.get(s, 0)) for s in sponsors.STATUSES},
        inquiries=[_out(db, i) for i in db.scalars(q)],
    )


@router.post("", response_model=InquiryOut, status_code=201)
def add_inquiry(
    body: InquiryIn, user: Operator, db: DbSession, settings: AppSettings
) -> InquiryOut:
    try:
        inq = sponsors.add(
            db, settings, body.body, body.sender, body.subject, body.project_id, user.id
        )
    except sponsors.SponsorError as exc:
        raise HTTPException(exc.status_code, detail=exc.message) from exc
    audit.record(
        db, "sponsor.add", user_id=user.id, entity_type="sponsor_inquiry", entity_id=inq.id,
        after={"brand": inq.brand, "category": inq.category},
    )  # fmt: skip
    db.commit()
    return _out(db, inq)


@router.patch("/{inquiry_id}", response_model=InquiryOut)
def update_inquiry(
    inquiry_id: int, body: InquiryPatch, user: Operator, db: DbSession, settings: AppSettings
) -> InquiryOut:
    inq = _get(db, inquiry_id)
    data = body.model_dump(exclude_unset=True)
    if "status" in data:
        if data["status"] not in sponsors.STATUSES:
            raise HTTPException(422, detail="Unbekannter Status")
        inq.status = data["status"]
    if "draft" in data and data["draft"] is not None:
        inq.draft, inq.draft_source = data["draft"].strip(), "manual"
    if "price_eur" in data:
        inq.price_eur = data["price_eur"]
    if "note" in data:
        inq.note = (data["note"] or "").strip() or None
    if "project_id" in data and data["project_id"] != inq.content_project_id:
        if data["project_id"] is not None and db.get(ContentProject, data["project_id"]) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Themenbereich nicht gefunden")
        inq.content_project_id, inq.fit_score = data["project_id"], 100
        sponsors.refresh(db, settings, inq, user.id)
    audit.record(
        db, "sponsor.update", user_id=user.id, entity_type="sponsor_inquiry", entity_id=inq.id,
        after={k: v for k, v in data.items() if k in ("status", "project_id")},
    )  # fmt: skip
    db.commit()
    return _out(db, inq)


@router.post("/{inquiry_id}/redraft", response_model=InquiryOut)
def redraft(inquiry_id: int, user: Operator, db: DbSession, settings: AppSettings) -> InquiryOut:
    inq = _get(db, inquiry_id)
    sponsors.refresh(db, settings, inq, user.id)
    db.commit()
    return _out(db, inq)


@router.delete("/{inquiry_id}", status_code=204)
def delete_inquiry(inquiry_id: int, user: Operator, db: DbSession) -> None:
    inq = _get(db, inquiry_id)
    db.delete(inq)
    audit.record(
        db, "sponsor.delete", user_id=user.id, entity_type="sponsor_inquiry", entity_id=inquiry_id
    )
    db.commit()
