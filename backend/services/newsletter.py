"""Newsletter sign-up with double opt-in (Ausbau A8).

1. The form on the bio page stores the address as ``pending`` with a random
   confirmation token (only its SHA-256 is stored) and writes a confirmation mail.
2. The link in that mail opens a page with a button; only the button (POST)
   confirms, so mail scanners that open links do not sign anybody up.
3. Every mail carries an unsubscribe link (also a page with a button).

Stored are only address, language, topic area, the consent text and the times.
Unconfirmed sign-ups are deleted after ``NEWSLETTER_PENDING_DAYS``. The answer
to the form is the same whether the address is new or known, so the form does
not tell strangers who is subscribed.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import Language
from models.channels import Channel
from models.marketing import BioPage, NewsletterSubscriber
from services import biolinks, mailer

EMAIL_RE = re.compile(r"^[^@\s<>\"',;]{1,64}@[A-Za-z0-9.-]{1,252}\.[A-Za-z]{2,24}$")
RESEND_AFTER = timedelta(minutes=10)
#: Unsubscribed addresses are deleted after this many days.
UNSUBSCRIBED_KEEP_DAYS = 30


class NewsletterError(ValueError):
    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def link(settings: Settings, path: str) -> str:
    base = settings.public_links_base_url.rstrip("/")
    return f"{base}{path}" if base else f"/api/public{path}"


MAIL = {
    Language.DE: (
        "Bitte bestätige deine Anmeldung",
        "Hallo,\n\ndu hast dich auf der Linkseite von {name} für den Newsletter angemeldet. "
        "Bitte bestätige das mit diesem Link:\n\n{confirm}\n\nWenn du das nicht warst, "
        "ignoriere diese Mail einfach. Ohne Bestätigung löschen wir die Adresse nach "
        "{days} Tagen.\n\nAbmelden: {unsubscribe}\n",
    ),
    Language.EN: (
        "Please confirm your sign-up",
        "Hi,\n\nyou signed up for the newsletter on the link page of {name}. Please "
        "confirm with this link:\n\n{confirm}\n\nIf that was not you, just ignore this "
        "email. Without confirmation the address is deleted after {days} days.\n\n"
        "Unsubscribe: {unsubscribe}\n",
    ),
}


def subscribe(
    session: Session,
    settings: Settings,
    page: BioPage,
    email: str,
    consent: bool,
    now: datetime | None = None,
) -> NewsletterSubscriber | None:
    """Sign up (or re-send the confirmation); None when nothing needed to happen."""
    now = now or datetime.now(UTC)
    if not page.enabled or not page.newsletter_enabled:
        raise NewsletterError("Newsletter ist hier nicht verfügbar", 404)
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise NewsletterError("Bitte eine gültige E-Mail-Adresse eingeben")
    if not consent:
        raise NewsletterError("Bitte die Einwilligung ankreuzen")
    channel = session.get(Channel, page.channel_id)
    assert channel is not None
    recent = session.scalar(
        select(func.count(NewsletterSubscriber.id)).where(
            NewsletterSubscriber.channel_id == channel.id,
            NewsletterSubscriber.updated_at >= now - timedelta(hours=1),
        )
    )
    if (recent or 0) >= settings.newsletter_signups_per_hour:
        raise NewsletterError("Gerade zu viele Anmeldungen, bitte später noch einmal", 429)
    sub = session.scalar(
        select(NewsletterSubscriber).where(
            NewsletterSubscriber.content_project_id == channel.content_project_id,
            NewsletterSubscriber.email == email,
        )
    )
    if sub is not None and sub.status == "confirmed":
        return None
    if sub is not None and sub.status == "pending" and now - sub.updated_at < RESEND_AFTER:
        return None
    text = biolinks.TEXT[channel.language]["consent"]
    confirm, unsubscribe = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    if sub is None:
        sub = NewsletterSubscriber(
            content_project_id=channel.content_project_id, email=email,
            language=channel.language, unsubscribe_token_hash=_hash(unsubscribe),
            consent_text=text, status="pending",
        )  # fmt: skip
        session.add(sub)
    sub.channel_id, sub.status, sub.consent_text = channel.id, "pending", text
    sub.confirm_token_hash, sub.unsubscribe_token_hash = _hash(confirm), _hash(unsubscribe)
    sub.unsubscribed_at, sub.updated_at = None, now
    session.flush()
    subject, body = MAIL[channel.language]
    unsubscribe_url = link(settings, f"/n/unsubscribe/{unsubscribe}")
    mailer.send(
        session, settings, email, subject,
        body.format(
            name=page.headline, confirm=link(settings, f"/n/confirm/{confirm}"),
            unsubscribe=unsubscribe_url, days=settings.newsletter_pending_days,
        ),
        kind="newsletter_confirm",
        headers={"List-Unsubscribe": f"<{unsubscribe_url}>"},
    )  # fmt: skip
    return sub


def by_confirm_token(session: Session, token: str) -> NewsletterSubscriber | None:
    return session.scalar(
        select(NewsletterSubscriber).where(NewsletterSubscriber.confirm_token_hash == _hash(token))
    )


def by_unsubscribe_token(session: Session, token: str) -> NewsletterSubscriber | None:
    return session.scalar(
        select(NewsletterSubscriber).where(
            NewsletterSubscriber.unsubscribe_token_hash == _hash(token)
        )
    )


def confirm(session: Session, token: str, now: datetime | None = None) -> NewsletterSubscriber:
    sub = by_confirm_token(session, token)
    if sub is None:
        raise NewsletterError("Link ist ungültig oder schon benutzt", 404)
    sub.status, sub.confirmed_at = "confirmed", now or datetime.now(UTC)
    sub.confirm_token_hash = None
    session.flush()
    return sub


def unsubscribe(session: Session, token: str, now: datetime | None = None) -> NewsletterSubscriber:
    sub = by_unsubscribe_token(session, token)
    if sub is None:
        raise NewsletterError("Link ist ungültig", 404)
    sub.status, sub.unsubscribed_at = "unsubscribed", now or datetime.now(UTC)
    sub.confirm_token_hash = None
    session.flush()
    return sub


def cleanup(session: Session, settings: Settings, now: datetime | None = None) -> int:
    """Delete sign-ups never confirmed and addresses unsubscribed long ago."""
    limit = (now or datetime.now(UTC)) - timedelta(days=settings.newsletter_pending_days)
    gone = (now or datetime.now(UTC)) - timedelta(days=UNSUBSCRIBED_KEEP_DAYS)
    result = session.execute(
        delete(NewsletterSubscriber).where(
            ((NewsletterSubscriber.status == "pending") & (NewsletterSubscriber.updated_at < limit))
            | (
                (NewsletterSubscriber.status == "unsubscribed")
                & (NewsletterSubscriber.unsubscribed_at < gone)
            )
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)
