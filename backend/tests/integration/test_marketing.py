"""Ausbau A8: campaign fit per topic area, affiliate links, bio pages, newsletter."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import access_guard
from core.config import get_settings
from core.enums import (
    ChannelSetupStatus,
    MetricWindow,
    PlatformCode,
    PublishingJobStatus,
    PublishingMode,
    UserRole,
)
from models import User
from models.analytics import Metric
from models.channel_setup import ChannelSetupTask
from models.channels import Channel
from models.marketing import AffiliateLink, BioPage, NewsletterSubscriber, OutgoingMail
from models.production import Variant
from models.publishing import Post, PublishingJob
from models.trends import Game
from services import affiliate, biolinks, campaign_fit, crosspost, mailer, newsletter
from tests.conftest import login
from tests.factories import Chain, build_chain

pytestmark = pytest.mark.integration


def _page(db: Session, channel: Channel, enabled: bool = True) -> BioPage:
    biolinks.ensure_pages(db)
    page = db.scalar(select(BioPage).where(BioPage.channel_id == channel.id))
    assert page is not None
    page.enabled = enabled
    db.flush()
    return page


def _link(db: Session, channel: Channel, **kw: object) -> AffiliateLink:
    link = AffiliateLink(content_project_id=channel.content_project_id, title="", url="")
    affiliate.apply_fields(
        link,
        {
            "title": "Mein Headset",
            "url": "https://partner.example/headset?tag=x",
            "keywords": ["Test Game"],
            "in_posts": True,
            **kw,
        },
    )
    db.add(link)
    db.flush()
    return link


# --- affiliate in posts ----------------------------------------------------------------


def test_affiliate_hint_needs_opt_in_bio_page_and_keyword(db: Session) -> None:
    chain = build_chain(db)
    v = chain.variant
    v.title, v.description = "Test Game: Clutch", "Runde 13"
    _link(db, chain.channel)
    assert affiliate.apply_texts(db, v) is False  # bio page still off
    _page(db, chain.channel)
    assert affiliate.apply_texts(db, v) is True
    assert v.description.startswith("Anzeige: Mein Headset – Link in meiner Bio\n")
    assert v.publish_options["commercial_content"] is True
    assert affiliate.text_problem(v) is None
    assert affiliate.apply_texts(db, v) is False  # idempotent
    assert v.description.count("Anzeige") == 1
    v.description = "Runde 13"  # label removed by hand -> blocked
    assert affiliate.text_problem(v) == "Werbehinweis „Anzeige“ fehlt am Anfang der Beschreibung"

    other = build_chain(db)
    other.variant.title = "Ganz anderes Thema"
    assert affiliate.apply_texts(db, other.variant) is False  # no keyword


def test_affiliate_off_in_posts_and_copy_without_bio_page(db: Session) -> None:
    chain = build_chain(db)
    chain.variant.title = "Test Game Moment"
    _page(db, chain.channel)
    link = _link(db, chain.channel, in_posts=False)
    assert affiliate.apply_texts(db, chain.variant) is False
    link.in_posts = True
    assert affiliate.apply_texts(db, chain.variant) is True
    target = db.scalars(
        select(Channel).where(
            Channel.content_project_id == chain.channel.content_project_id,
            Channel.language == chain.channel.language,
            Channel.id != chain.channel.id,
        )
    ).first()
    assert target is not None
    _page(db, target, enabled=False)
    copy = crosspost.copy_to(db, _ready(chain), target)
    assert not isinstance(copy, str)
    assert "Anzeige" not in (copy.description or "")
    assert "affiliate_link_id" not in copy.concept
    assert "commercial_content" not in copy.publish_options


def _ready(chain: Chain) -> Variant:
    chain.clip.duration_s = 20.0
    return chain.variant


def test_affiliate_url_must_be_https() -> None:
    link = AffiliateLink(content_project_id=1, title="", url="")
    with pytest.raises(affiliate.AffiliateError):
        affiliate.apply_fields(link, {"title": "X", "url": "http://plain.example"})
    with pytest.raises(affiliate.AffiliateError):
        affiliate.apply_fields(link, {"title": "X", "url": "javascript:alert(1)"})


# --- bio pages -------------------------------------------------------------------------


def test_pages_exist_for_every_channel_but_start_switched_off(db: Session) -> None:
    chain = build_chain(db)
    biolinks.ensure_pages(db)
    pages = db.scalars(select(BioPage)).all()
    assert len(pages) == len(db.scalars(select(Channel)).all())
    assert not any(p.enabled for p in pages)
    assert len({p.slug for p in pages}) == len(pages)
    page = _page(db, chain.channel)
    with pytest.raises(biolinks.BioError):
        biolinks.update(db, page, {"slug": "Nope Nope"})
    with pytest.raises(biolinks.BioError):
        biolinks.update(db, page, {"slug": "go"})
    with pytest.raises(biolinks.BioError):
        biolinks.update(db, page, {"links": [{"title": "X", "url": "ftp://a"}]})
    other = next(p for p in pages if p.id != page.id)
    with pytest.raises(biolinks.BioError):
        biolinks.update(db, page, {"slug": other.slug})
    biolinks.update(
        db,
        page,
        {"slug": "clutch-de", "links": [{"title": "Discord", "url": "https://discord.example/x"}]},
    )
    assert page.slug == "clutch-de"


def _mock_post(db: Session, chain: Chain, url: str, real: bool, views: int = 0) -> Post:
    v = chain.variant
    job = PublishingJob(
        variant_id=v.id,
        channel_id=v.channel_id,
        status=PublishingJobStatus.SUCCEEDED,
        mode=PublishingMode.MOCK,
        scheduled_for=datetime.now(UTC),
        idempotency_key=f"m-{v.id}-{url}",
    )
    db.add(job)
    db.flush()
    post = Post(
        publishing_job_id=job.id,
        variant_id=v.id,
        channel_id=v.channel_id,
        external_post_id=f"x-{v.id}",
        published_at=datetime.now(UTC),
        is_mock=not real,
        url=url,
    )
    db.add(post)
    db.flush()
    if views:
        db.add(
            Metric(
                post_id=post.id,
                measure_window=MetricWindow.H48,
                views=views,
                measured_at=datetime.now(UTC),
            )
        )
        db.flush()
    return post


def test_public_page_shows_profiles_videos_and_labelled_ads(api: TestClient, db: Session) -> None:
    chain = build_chain(db)
    chain.variant.title = "Echter Clip"
    _mock_post(db, chain, "https://youtu.be/real", real=True)
    other = build_chain(db)
    other.variant.title = "Testclip"
    _mock_post(db, other, "https://youtu.be/mock", real=False)
    yt = chain.channel
    tiktok = db.scalars(
        select(Channel).where(
            Channel.content_project_id == yt.content_project_id,
            Channel.language == yt.language,
            Channel.id != yt.id,
        )
    ).first()
    assert tiktok is not None
    db.add(
        ChannelSetupTask(
            content_project_id=yt.content_project_id,
            platform=tiktok.platform.code,
            language=tiktok.language,
            status=ChannelSetupStatus.DONE,
            display_name="X",
            handle="clutchde",
            bio="b",
            channel_id=tiktok.id,
        )
    )
    link = _link(db, yt)
    page = _page(db, yt)
    page.headline = "Clutch <DE>"
    db.commit()

    r = api.get(f"/api/public/l/{page.slug}")
    assert r.status_code == 200
    body = r.text
    assert "Clutch &lt;DE&gt;" in body and "<DE>" not in body
    assert "https://youtu.be/real" in body and "youtu.be/mock" not in body
    assert f"/api/public/go/{link.id}?c={yt.id}" in body
    assert 'rel="sponsored nofollow noopener"' in body and ">Anzeige<" in body
    assert "Affiliate-Links" in body
    if tiktok.platform.code == PlatformCode.TIKTOK:
        assert "https://www.tiktok.com/@clutchde" in body
    assert "<script" not in body
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert 'action="/api/public/l/' in body
    via_public = api.get(f"/api/public/l/{page.slug}", headers={"X-Public-Entry": "1"})
    assert f'action="/l/{page.slug}/newsletter"' in via_public.text
    db.refresh(page)
    assert page.views == 2

    page.enabled = False
    db.commit()
    assert api.get(f"/api/public/l/{page.slug}").status_code == 404

    go = api.get(f"/api/public/go/{link.id}?c={yt.id}", follow_redirects=False)
    assert go.status_code == 302 and go.headers["location"] == link.url
    db.refresh(link)
    assert link.clicks == 1
    assert api.get(f"/api/public/go/{link.id + 999}", follow_redirects=False).status_code == 404


# --- newsletter ------------------------------------------------------------------------


def _token(mail: OutgoingMail, kind: str) -> str:
    found = re.search(rf"/n/{kind}/([A-Za-z0-9_-]+)", mail.body_text)
    assert found is not None
    return found.group(1)


def test_double_opt_in_confirm_and_unsubscribe(api: TestClient, db: Session) -> None:
    chain = build_chain(db)
    page = _page(db, chain.channel)
    db.commit()
    url = f"/api/public/l/{page.slug}/newsletter"

    missing = api.post(url, data={"email": "fan@example.com"})
    assert missing.status_code == 422 and "Einwilligung" in missing.text
    assert api.post(url, data={"email": "kein-mail", "consent": "yes"}).status_code == 422

    bot = api.post(url, data={"email": "bot@example.com", "consent": "yes", "website": "x"})
    assert bot.status_code == 200
    assert (
        db.scalar(
            select(NewsletterSubscriber).where(NewsletterSubscriber.email == "bot@example.com")
        )
        is None
    )

    ok = api.post(url, data={"email": "Fan@Example.com ", "consent": "yes"})
    assert ok.status_code == 200 and "Fast geschafft" in ok.text
    sub = db.scalar(
        select(NewsletterSubscriber).where(NewsletterSubscriber.email == "fan@example.com")
    )
    assert sub is not None and sub.status == "pending" and "Newsletter" in sub.consent_text
    mail = db.scalars(select(OutgoingMail).where(OutgoingMail.kind == "newsletter_confirm")).one()
    assert mail.status == "mock" and mail.to_address == "fan@example.com"
    token = _token(mail, "confirm")
    assert token not in (sub.confirm_token_hash or "")  # only the hash is stored

    # the same address again within minutes: no second mail, same answer
    again = api.post(url, data={"email": "fan@example.com", "consent": "yes"})
    assert again.status_code == 200
    assert len(db.scalars(select(OutgoingMail)).all()) == 1

    show = api.get(f"/api/public/n/confirm/{token}")
    assert show.status_code == 200 and "<button" in show.text
    db.refresh(sub)
    assert sub.status == "pending"  # opening the link alone does not confirm
    done = api.post(f"/api/public/n/confirm/{token}")
    assert done.status_code == 200 and "bestätigt" in done.text
    db.refresh(sub)
    assert sub.status == "confirmed" and sub.confirmed_at is not None
    assert api.post(f"/api/public/n/confirm/{token}").status_code == 404  # used up

    stop = _token(mail, "unsubscribe")
    assert api.get(f"/api/public/n/unsubscribe/{stop}").status_code == 200
    assert api.post(f"/api/public/n/unsubscribe/{stop}").status_code == 200
    db.refresh(sub)
    assert sub.status == "unsubscribed"


def test_cleanup_and_rate_limit(db: Session) -> None:
    settings = get_settings().model_copy(update={"newsletter_signups_per_hour": 2})
    chain = build_chain(db)
    page = _page(db, chain.channel)
    for i in range(2):
        assert newsletter.subscribe(db, settings, page, f"a{i}@example.com", True) is not None
    with pytest.raises(newsletter.NewsletterError) as err:
        newsletter.subscribe(db, settings, page, "a9@example.com", True)
    assert err.value.status_code == 429
    later = datetime.now(UTC) + timedelta(days=settings.newsletter_pending_days + 1)
    assert newsletter.cleanup(db, settings, now=later) == 2
    assert mailer.cleanup(db, now=later + timedelta(days=30)) == 2
    page.newsletter_enabled = False
    with pytest.raises(newsletter.NewsletterError):
        newsletter.subscribe(db, settings, page, "b@example.com", True)


def test_mail_mode_smtp_without_host_stays_in_outbox(db: Session) -> None:
    settings = get_settings().model_copy(update={"mail_mode": "smtp", "smtp_host": ""})
    mail = mailer.send(db, settings, "x@example.com", "Hi", "Text", kind="test")
    assert mail.status == "mock" and mail.error == "SMTP_HOST oder MAIL_FROM fehlt"


# --- campaign fit ----------------------------------------------------------------------


def test_campaign_fit_prefers_gaming_area_and_estimates_payout(db: Session) -> None:
    chain = build_chain(db)
    for views in (10_000, 20_000, 30_000):
        _mock_post(db, build_chain(db), f"https://y/{views}", real=True, views=views)
    game = db.get(Game, chain.gameplay_file.game_id)
    assert game is not None
    fits = campaign_fit.rank(
        db,
        {
            "name": "Clips von Streamer X",
            "brief": f"Clips aus {game.name}",
            "platforms": [chain.channel.platform.code.value],
            "languages": ["de"],
            "cpm_usd": Decimal("1.40"),
        },
    )
    best = fits[0]
    assert best.project_id == chain.channel.content_project_id
    assert best.score >= 75 and any("passende Kanäle" in r for r in best.reasons)
    assert best.median_views is not None
    assert best.usd_per_clip == pytest.approx(best.median_views / 1000 * 1.40 * 0.9, abs=0.01)


# --- API -------------------------------------------------------------------------------


def test_api_pages_affiliates_newsletter_and_rights(
    api: TestClient, db: Session, make_user: Callable[..., User]
) -> None:
    chain = build_chain(db)
    make_user(email="op@example.com", role=UserRole.OPERATOR)
    make_user(email="viewer@example.com", role=UserRole.VIEWER)
    db.commit()
    viewer = login(api, "viewer@example.com")
    pages = api.get("/api/bio-pages").json()
    assert pages and all(not p["enabled"] for p in pages)
    assert api.get("/api/newsletter").status_code == 403  # addresses: operators only
    assert api.get("/api/mail/outbox").status_code == 403
    assert (
        api.patch(
            f"/api/bio-pages/{pages[0]['id']}", json={"enabled": True}, headers=viewer
        ).status_code
        == 403
    )

    h = login(api, "op@example.com")
    page = next(p for p in pages if p["channel_id"] == chain.channel.id)
    r = api.patch(
        f"/api/bio-pages/{page['id']}", json={"enabled": True, "slug": "mein-kanal"}, headers=h
    )
    assert r.status_code == 200, r.text
    assert r.json()["preview_path"] == "/api/public/l/mein-kanal"
    bad = api.patch(f"/api/bio-pages/{page['id']}", json={"slug": "X Y"}, headers=h)
    assert bad.status_code == 422

    made = api.post(
        "/api/affiliate-links",
        json={
            "project_id": chain.channel.content_project_id,
            "title": "Maus",
            "url": "https://partner.example/m",
            "keywords": ["Maus", "maus", " "],
        },
        headers=h,
    )
    assert made.status_code == 201, made.text
    assert made.json()["keywords"] == ["Maus"] and made.json()["in_posts"] is False
    link_id = made.json()["id"]
    assert (
        api.patch(
            f"/api/affiliate-links/{link_id}", json={"url": "http://x"}, headers=h
        ).status_code
        == 422
    )
    assert api.patch(f"/api/affiliate-links/{link_id}", json={"in_posts": True}, headers=h).json()[
        "in_posts"
    ]
    assert len(api.get("/api/affiliate-links").json()) == 1

    api.post(
        "/api/public/l/mein-kanal/newsletter", data={"email": "f@example.com", "consent": "yes"}
    )
    news = api.get("/api/newsletter").json()
    assert news["pending"] == 1 and news["subscribers"][0]["email"] == "f@example.com"
    box = api.get("/api/mail/outbox").json()
    assert box["mode"] == "mock" and box["mails"][0]["kind"] == "newsletter_confirm"
    sub_id = news["subscribers"][0]["id"]
    assert api.delete(f"/api/newsletter/{sub_id}", headers=h).status_code == 204
    assert api.delete(f"/api/affiliate-links/{link_id}", headers=h).status_code == 204

    fit = api.post(
        "/api/campaigns/match",
        json={
            "name": "Gaming Clips",
            "platforms": ["youtube"],
            "languages": ["de"],
            "cpm_usd": 1.4,
        },
        headers=h,
    )
    assert fit.status_code == 200 and fit.json()[0]["score"] > 0


def test_public_paths_skip_cloudflare_access() -> None:
    assert access_guard.is_exempt("/api/public/l/abc")
    assert not access_guard.is_exempt("/api/publicx")
    assert not access_guard.is_exempt("/api/bio-pages")
