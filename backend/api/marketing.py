"""Bio-link pages, affiliate links, newsletter and outbox in the dashboard (Ausbau A8)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from api.deps import AppSettings, DbSession, Operator, Viewer, csrf_protect
from core.enums import Language
from models.channels import Channel
from models.marketing import AffiliateLink, BioPage, NewsletterSubscriber, OutgoingMail
from models.projects import ContentProject
from services import affiliate, audit, biolinks, mailer, weekly_report

router = APIRouter(tags=["marketing"], dependencies=[Depends(csrf_protect)])


class LinkItem(BaseModel):
    title: str = Field(max_length=80)
    url: str = Field(max_length=1000)


class BioPageOut(BaseModel):
    id: int
    channel_id: int
    channel: str
    platform: str
    language: str
    project_id: int
    project: str
    slug: str
    enabled: bool
    headline: str
    intro: str | None
    links: list[LinkItem]
    show_videos: bool
    newsletter_enabled: bool
    views: int
    public_url: str | None
    preview_path: str
    subscribers: int


class BioPagePatch(BaseModel):
    slug: str | None = Field(default=None, max_length=60)
    enabled: bool | None = None
    headline: str | None = Field(default=None, max_length=120)
    intro: str | None = Field(default=None, max_length=600)
    links: list[LinkItem] | None = None
    show_videos: bool | None = None
    newsletter_enabled: bool | None = None


class AffiliateIn(BaseModel):
    project_id: int
    title: str = Field(min_length=1, max_length=120)
    url: str = Field(max_length=1000)
    program: str | None = Field(default=None, max_length=80)
    language: Language | None = None
    keywords: list[str] = Field(default_factory=list, max_length=20)
    in_posts: bool = False
    active: bool = True
    note: str | None = Field(default=None, max_length=2000)


class AffiliatePatch(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    url: str | None = Field(default=None, max_length=1000)
    program: str | None = Field(default=None, max_length=80)
    language: Language | None = None
    keywords: list[str] | None = Field(default=None, max_length=20)
    in_posts: bool | None = None
    active: bool | None = None
    note: str | None = Field(default=None, max_length=2000)


class AffiliateOut(BaseModel):
    id: int
    project_id: int
    project: str
    title: str
    url: str
    program: str | None
    language: str | None
    keywords: list[str]
    in_posts: bool
    active: bool
    clicks: int
    note: str | None


class SubscriberOut(BaseModel):
    id: int
    project_id: int
    channel_id: int | None
    email: str
    language: str
    status: str
    created_at: datetime
    confirmed_at: datetime | None


class NewsletterOut(BaseModel):
    confirmed: int
    pending: int
    unsubscribed: int
    subscribers: list[SubscriberOut]


class MailOut(BaseModel):
    id: int
    to_address: str
    subject: str
    body_text: str
    kind: str
    status: str
    error: str | None
    created_at: datetime
    sent_at: datetime | None


class OutboxOut(BaseModel):
    mode: str
    problem: str | None
    mails: list[MailOut]


def _fail(exc: Any) -> HTTPException:
    return HTTPException(exc.status_code, detail=exc.message)


def _page_out(db: DbSession, settings: AppSettings, page: BioPage) -> BioPageOut:
    channel = db.get(Channel, page.channel_id)
    assert channel is not None
    subs = db.scalar(
        select(func.count(NewsletterSubscriber.id)).where(
            NewsletterSubscriber.channel_id == channel.id,
            NewsletterSubscriber.status == "confirmed",
        )
    )
    return BioPageOut(
        id=page.id, channel_id=channel.id, channel=channel.name,
        platform=channel.platform.code.value, language=channel.language.value,
        project_id=channel.content_project_id, project=channel.content_project.name,
        slug=page.slug, enabled=page.enabled, headline=page.headline, intro=page.intro,
        links=[LinkItem(**x) for x in page.links or []], show_videos=page.show_videos,
        newsletter_enabled=page.newsletter_enabled, views=page.views,
        public_url=biolinks.public_url(settings, page),
        preview_path=f"/api/public/l/{page.slug}", subscribers=int(subs or 0),
    )  # fmt: skip


@router.get("/bio-pages", response_model=list[BioPageOut])
def list_pages(
    _: Viewer, db: DbSession, settings: AppSettings, project_id: int | None = None
) -> list[BioPageOut]:
    if biolinks.ensure_pages(db):
        db.commit()
    q = select(BioPage).join(Channel, Channel.id == BioPage.channel_id).order_by(Channel.id)
    if project_id is not None:
        q = q.where(Channel.content_project_id == project_id)
    return [_page_out(db, settings, p) for p in db.scalars(q)]


@router.patch("/bio-pages/{page_id}", response_model=BioPageOut)
def update_page(
    page_id: int, body: BioPagePatch, user: Operator, db: DbSession, settings: AppSettings
) -> BioPageOut:
    page = db.get(BioPage, page_id)
    if page is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Linkseite nicht gefunden")
    data = body.model_dump(exclude_unset=True)
    if "links" in data and data["links"] is not None:
        data["links"] = [dict(x) for x in data["links"]]
    try:
        biolinks.update(db, page, data)
    except biolinks.BioError as exc:
        db.rollback()
        raise _fail(exc) from exc
    audit.record(
        db, "bio_page.update", user_id=user.id, entity_type="bio_page", entity_id=page.id,
        after={k: v for k, v in data.items() if k != "links"},
    )  # fmt: skip
    db.commit()
    return _page_out(db, settings, page)


def _aff_out(db: DbSession, link: AffiliateLink) -> AffiliateOut:
    project = db.get(ContentProject, link.content_project_id)
    return AffiliateOut(
        id=link.id, project_id=link.content_project_id, project=project.name if project else "",
        title=link.title, url=link.url, program=link.program,
        language=link.language.value if link.language else None,
        keywords=[str(k) for k in link.keywords or []], in_posts=link.in_posts,
        active=link.active, clicks=link.clicks, note=link.note,
    )  # fmt: skip


@router.get("/affiliate-links", response_model=list[AffiliateOut])
def list_affiliates(_: Viewer, db: DbSession, project_id: int | None = None) -> list[AffiliateOut]:
    q = select(AffiliateLink).order_by(AffiliateLink.id)
    if project_id is not None:
        q = q.where(AffiliateLink.content_project_id == project_id)
    return [_aff_out(db, a) for a in db.scalars(q)]


@router.post("/affiliate-links", response_model=AffiliateOut, status_code=201)
def create_affiliate(body: AffiliateIn, user: Operator, db: DbSession) -> AffiliateOut:
    if db.get(ContentProject, body.project_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Themenbereich nicht gefunden")
    link = AffiliateLink(content_project_id=body.project_id, title="", url="")
    try:
        affiliate.apply_fields(link, body.model_dump(exclude={"project_id"}))
    except affiliate.AffiliateError as exc:
        raise _fail(exc) from exc
    db.add(link)
    db.flush()
    audit.record(
        db, "affiliate.create", user_id=user.id, entity_type="affiliate_link",
        entity_id=link.id, after={"title": link.title, "program": link.program},
    )  # fmt: skip
    db.commit()
    return _aff_out(db, link)


@router.patch("/affiliate-links/{link_id}", response_model=AffiliateOut)
def update_affiliate(
    link_id: int, body: AffiliatePatch, user: Operator, db: DbSession
) -> AffiliateOut:
    link = db.get(AffiliateLink, link_id)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Link nicht gefunden")
    data = body.model_dump(exclude_unset=True)
    try:
        affiliate.apply_fields(link, data)
    except affiliate.AffiliateError as exc:
        db.rollback()
        raise _fail(exc) from exc
    audit.record(
        db, "affiliate.update", user_id=user.id, entity_type="affiliate_link",
        entity_id=link.id, after={k: v for k, v in data.items() if k != "note"},
    )  # fmt: skip
    db.commit()
    return _aff_out(db, link)


@router.delete("/affiliate-links/{link_id}", status_code=204)
def delete_affiliate(link_id: int, user: Operator, db: DbSession) -> None:
    link = db.get(AffiliateLink, link_id)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Link nicht gefunden")
    db.delete(link)
    audit.record(
        db, "affiliate.delete", user_id=user.id, entity_type="affiliate_link", entity_id=link_id
    )
    db.commit()


@router.get("/newsletter", response_model=NewsletterOut)
def newsletter(
    _: Operator, db: DbSession, project_id: int | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
) -> NewsletterOut:  # fmt: skip
    """Addresses are personal data: only operators and admins see them."""
    where = [] if project_id is None else [NewsletterSubscriber.content_project_id == project_id]
    counts = dict(
        db.execute(
            select(NewsletterSubscriber.status, func.count(NewsletterSubscriber.id))
            .where(*where)
            .group_by(NewsletterSubscriber.status)
        ).all()
    )
    rows = db.scalars(
        select(NewsletterSubscriber)
        .where(*where)
        .order_by(NewsletterSubscriber.id.desc())
        .limit(limit)
    )
    return NewsletterOut(
        confirmed=int(counts.get("confirmed", 0)), pending=int(counts.get("pending", 0)),
        unsubscribed=int(counts.get("unsubscribed", 0)),
        subscribers=[
            SubscriberOut(
                id=s.id, project_id=s.content_project_id, channel_id=s.channel_id,
                email=s.email, language=s.language.value, status=s.status,
                created_at=s.created_at, confirmed_at=s.confirmed_at,
            )
            for s in rows
        ],
    )  # fmt: skip


@router.delete("/newsletter/{subscriber_id}", status_code=204)
def delete_subscriber(subscriber_id: int, user: Operator, db: DbSession) -> None:
    """Delete an address completely (request for erasure)."""
    sub = db.get(NewsletterSubscriber, subscriber_id)
    if sub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Adresse nicht gefunden")
    db.delete(sub)
    audit.record(
        db, "newsletter.delete", user_id=user.id, entity_type="newsletter_subscriber",
        entity_id=subscriber_id,
    )  # fmt: skip
    db.commit()


@router.get("/mail/outbox", response_model=OutboxOut)
def outbox(
    _: Operator, db: DbSession, settings: AppSettings,
    limit: int = Query(default=50, ge=1, le=500),
) -> OutboxOut:  # fmt: skip
    mails = db.scalars(select(OutgoingMail).order_by(OutgoingMail.id.desc()).limit(limit))
    return OutboxOut(
        mode=settings.mail_mode,
        problem=mailer.ready(settings),
        mails=[
            MailOut(
                id=m.id, to_address=m.to_address, subject=m.subject, body_text=m.body_text,
                kind=m.kind, status=m.status, error=m.error, created_at=m.created_at,
                sent_at=m.sent_at,
            )
            for m in mails
        ],
    )  # fmt: skip


class WeeklyReportOut(BaseModel):
    subject: str
    text: str
    recipient: str | None
    mode: str
    problem: str | None
    schedule: str
    last_sent_at: datetime | None


@router.get("/reports/weekly", response_model=WeeklyReportOut)
def weekly_preview(_: Operator, db: DbSession, settings: AppSettings) -> WeeklyReportOut:
    """Preview of the weekly report as it would go out now (A10)."""
    report = weekly_report.build(db, settings)
    last = db.scalar(
        select(OutgoingMail.created_at)
        .where(OutgoingMail.kind == weekly_report.KIND)
        .order_by(OutgoingMail.id.desc())
        .limit(1)
    )
    problem = mailer.ready(settings) or (
        None if settings.report_email else "REPORT_EMAIL fehlt: Bericht nur im Postausgang"
    )
    when = f"{weekly_report.WEEKDAYS[settings.report_weekday]}s um {settings.report_hour} Uhr"
    return WeeklyReportOut(
        subject=report.subject, text=report.text, recipient=settings.report_email or None,
        mode=settings.mail_mode, problem=problem,
        schedule=when if settings.report_enabled else "ausgeschaltet", last_sent_at=last,
    )  # fmt: skip


@router.post("/reports/weekly/send", response_model=MailOut, status_code=201)
def weekly_send(user: Operator, db: DbSession, settings: AppSettings) -> MailOut:
    mail = weekly_report.send(db, settings)
    audit.record(
        db, "report.weekly", user_id=user.id, entity_type="outgoing_mail", entity_id=mail.id
    )
    db.commit()
    return MailOut(
        id=mail.id, to_address=mail.to_address, subject=mail.subject, body_text=mail.body_text,
        kind=mail.kind, status=mail.status, error=mail.error, created_at=mail.created_at,
        sent_at=mail.sent_at,
    )  # fmt: skip
