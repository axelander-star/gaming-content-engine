"""Public bio-link pages and newsletter double opt-in (Ausbau A8).

No login, no cookies, no scripts. Reached through its own host
(``links.<domain>`` -> Caddy ``:8082``), which forwards only these paths and
sets ``X-Public-Entry``; there the links on the page have no ``/api/public``
prefix. The paths are exempt from the Cloudflare Access check.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from api.deps import AppSettings, DbSession
from core.enums import Language
from models.channels import Channel
from models.marketing import AffiliateLink, BioPage
from services import biolinks, newsletter

router = APIRouter(prefix="/public", tags=["public"], include_in_schema=False)
HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
        "frame-ancestors 'none'; base-uri 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}
WORDS = {
    Language.DE: {
        "missing": ("Seite nicht gefunden", "Diese Linkseite gibt es nicht (mehr)."),
        "almost": ("Fast geschafft", "Wir haben dir eine Mail geschickt. Bitte bestätige "
                   "die Anmeldung mit dem Link darin."),
        "confirm_q": ("Anmeldung bestätigen", "Möchtest du den Newsletter bekommen?"),
        "confirm_btn": "Ja, bestätigen",
        "confirmed": ("Danke!", "Deine Anmeldung ist bestätigt. Abmelden geht jederzeit "
                      "über den Link in jeder Mail."),
        "unsub_q": ("Newsletter abbestellen", "Möchtest du keine Mails mehr bekommen?"),
        "unsub_btn": "Abbestellen",
        "unsubscribed": ("Abgemeldet", "Du bekommst keine Newsletter mehr."),
        "error": "Das hat nicht geklappt",
    },
    Language.EN: {
        "missing": ("Page not found", "This link page does not exist (any more)."),
        "almost": ("Almost done", "We sent you an email. Please confirm the sign-up with "
                   "the link in it."),
        "confirm_q": ("Confirm sign-up", "Do you want to get the newsletter?"),
        "confirm_btn": "Yes, confirm",
        "confirmed": ("Thank you!", "Your sign-up is confirmed. You can unsubscribe any "
                      "time with the link in every email."),
        "unsub_q": ("Unsubscribe", "Do you want to stop getting emails?"),
        "unsub_btn": "Unsubscribe",
        "unsubscribed": ("Unsubscribed", "You will not get the newsletter any more."),
        "error": "That did not work",
    },
}  # fmt: skip


def _prefix(request: Request) -> str:
    return "" if request.headers.get("x-public-entry") else "/api/public"


def _html(body: str, code: int = 200) -> HTMLResponse:
    return HTMLResponse(body, status_code=code, headers=HEADERS)


def _say(
    key: str, language: Language = Language.DE, code: int = 200, form: str = ""
) -> HTMLResponse:
    title, text = WORDS[language][key]
    return _html(biolinks.message(title, text, language, form), code)


def _page(db: DbSession, slug: str) -> tuple[BioPage, Channel] | None:
    page = db.scalar(select(BioPage).where(BioPage.slug == slug.lower()))
    if page is None or not page.enabled:
        return None
    channel = db.get(Channel, page.channel_id)
    return (page, channel) if channel is not None else None


@router.get("/l/{slug}", response_class=HTMLResponse)
def bio_page(slug: str, request: Request, db: DbSession, settings: AppSettings) -> HTMLResponse:
    found = _page(db, slug)
    if found is None:
        return _say("missing", code=404)
    page, _ = found
    page.views += 1
    db.commit()
    return _html(biolinks.render(biolinks.collect(db, page), settings, _prefix(request)))


@router.post("/l/{slug}/newsletter", response_class=HTMLResponse)
def sign_up(
    slug: str,
    request: Request,
    db: DbSession,
    settings: AppSettings,
    email: Annotated[str, Form(max_length=320)] = "",
    consent: Annotated[str, Form(max_length=10)] = "",
    website: Annotated[str, Form(max_length=200)] = "",
) -> HTMLResponse:
    found = _page(db, slug)
    if found is None:
        return _say("missing", code=404)
    page, channel = found
    if website:  # honeypot: bots fill every field; answer as if it worked
        return _say("almost", channel.language)
    try:
        newsletter.subscribe(db, settings, page, email, consent == "yes")
    except newsletter.NewsletterError as exc:
        db.rollback()
        data = biolinks.collect(db, page)
        notice = f"{WORDS[channel.language]['error']}: {exc.message}"
        return _html(biolinks.render(data, settings, _prefix(request), notice), exc.status_code)
    db.commit()
    return _say("almost", channel.language)


def _button(action: str, label: str) -> str:
    return (
        f'<form method="post" action="{action}" style="border:0;background:none">'
        f'<button type="submit">{biolinks._e(label)}</button></form>'
    )


@router.get("/n/confirm/{token}", response_class=HTMLResponse)
def confirm_page(token: str, request: Request, db: DbSession) -> HTMLResponse:
    """Only shows a button: mail scanners that open links must not confirm."""
    sub = newsletter.by_confirm_token(db, token)
    if sub is None:
        return _say("missing", code=404)
    words = WORDS[sub.language]
    action = f"{_prefix(request)}/n/confirm/{token}"
    return _say("confirm_q", sub.language, form=_button(action, str(words["confirm_btn"])))


@router.post("/n/confirm/{token}", response_class=HTMLResponse)
def confirm(token: str, db: DbSession) -> HTMLResponse:
    try:
        sub = newsletter.confirm(db, token)
    except newsletter.NewsletterError:
        return _say("missing", code=404)
    db.commit()
    return _say("confirmed", sub.language)


@router.get("/n/unsubscribe/{token}", response_class=HTMLResponse)
def unsubscribe_page(token: str, request: Request, db: DbSession) -> HTMLResponse:
    sub = newsletter.by_unsubscribe_token(db, token)
    if sub is None:
        return _say("missing", code=404)
    if sub.status == "unsubscribed":
        return _say("unsubscribed", sub.language)
    action = f"{_prefix(request)}/n/unsubscribe/{token}"
    return _say(
        "unsub_q", sub.language, form=_button(action, str(WORDS[sub.language]["unsub_btn"]))
    )


@router.post("/n/unsubscribe/{token}", response_class=HTMLResponse)
def unsubscribe(token: str, db: DbSession) -> HTMLResponse:
    """Also the target of one-click ``List-Unsubscribe`` in mail programs."""
    try:
        sub = newsletter.unsubscribe(db, token)
    except newsletter.NewsletterError:
        return _say("missing", code=404)
    db.commit()
    return _say("unsubscribed", sub.language)


@router.get("/go/{link_id}", response_model=None)
def go(link_id: int, db: DbSession, c: int | None = None) -> RedirectResponse | HTMLResponse:
    """Count the click (no cookie, no IP) and forward to the partner link."""
    link = db.get(AffiliateLink, link_id)
    if link is None or not link.active:
        return _say("missing", code=404)
    if c is not None:
        channel = db.get(Channel, c)
        if channel is None or channel.content_project_id != link.content_project_id:
            return _say("missing", code=404)
    link.clicks += 1
    db.commit()
    return RedirectResponse(link.url, status_code=302, headers={"Referrer-Policy": "no-referrer"})
