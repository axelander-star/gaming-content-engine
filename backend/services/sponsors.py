"""Sponsor inbox (Ausbau A9): sort brand inquiries, flag risks, suggest a price, draft a reply.

Nothing is sent. The operator pastes a mail (sender, subject, text); the engine

* sorts it: ``sponsoring`` (paid post), ``product_test`` (free product for a
  video), ``affiliate`` (commission only), ``spam`` or ``other``;
* flags what needs a second look: no payment, upfront fee, gambling/betting,
  crypto/trading, adult content, mass mail, very short deadline;
* picks the topic area whose words fit best;
* suggests a price per short from the area's own reach: median views per post
  across its channels times a CPM range (``CPM_EUR``), at least ``MIN_PRICE``;
  a bundle of three posts gets ``BUNDLE_DISCOUNT``. It is a starting point for
  the negotiation, written as such in the draft;
* writes a reply draft in the language of the inquiry (AI with the template as
  fallback): thank, price, what is included, that the post is marked as an ad,
  and what is still needed (brief, timing, usage rights). Spam gets no draft.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from email.utils import parseaddr
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import ContentProjectStatus, Language
from models.channels import Channel
from models.projects import ContentProject
from models.sponsors import SponsorInquiry
from services import ai, campaign_fit
from services.comments import fold, language_of

log = logging.getLogger(__name__)

#: Euro per 1,000 views for one sponsored short (integrated mention), low/typical/high.
CPM_EUR = (Decimal("10"), Decimal("15"), Decimal("25"))
MIN_PRICE = Decimal("50")
BUNDLE_POSTS = 3
BUNDLE_DISCOUNT = Decimal("0.10")
STATUSES = ("new", "replied", "won", "declined", "archived")
CATEGORY_LABELS = {
    "sponsoring": "Bezahlte Kooperation",
    "product_test": "Produkt zum Testen",
    "affiliate": "Nur Provision",
    "other": "Sonstiges",
    "spam": "Spam",
}

_SPONSOR = (
    "sponsor", "kooperation", "zusammenarbeit", "collaboration", "collab", "partnership",
    "partnerschaft", "paid", "bezahlt", "budget", "vergütung", "verguetung", "honorar", "fee",
    "rate card", "media kit", "mediakit", "integration", "werbepartner", "campaign", "kampagne",
    "brand deal", "promotion", "influencer",
)  # fmt: skip
_PRODUCT = (
    "produkt testen", "test product", "review", "kostenlos zuschicken", "free sample",
    "send you", "zuschicken", "gratis", "for free", "testgerät", "testgeraet", "unboxing",
)  # fmt: skip
_AFFILIATE = ("affiliate", "provision", "commission", "rabattcode", "discount code", "referral")
_SPAM = (
    "seo", "backlink", "guest post", "gastbeitrag", "followers kaufen", "buy followers",
    "grow your channel", "more subscribers", "mehr abonnenten", "web design", "webdesign",
    "lottery", "you have won", "inheritance", "erbschaft",
)  # fmt: skip
_FLAGS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Vorabzahlung verlangt", ("upfront", "vorab zahlen", "vorauszahlung", "registration fee",
                               "deposit", "anzahlung von dir", "pay first")),
    ("Glücksspiel oder Wetten: rechtlich heikel, oft für junges Publikum verboten",
     ("casino", "slots", "betting", "wetten", "sportwetten", "gambling", "glücksspiel",
      "gluecksspiel", "poker", "lootbox", "loot box", "skin gambling", "case opening")),
    ("Krypto oder Trading: hohe Haftungs- und Ruf-Risiken", ("crypto", "krypto", "bitcoin",
     "token", "nft", "forex", "trading", "web3", "airdrop")),
    ("Inhalt für Erwachsene", ("onlyfans", "adult", "erotik", "dating app", "18+")),
    ("Kein Geld, nur Produkt oder Reichweite", ("exposure", "reichweite statt", "unpaid",
     "unbezahlt", "no budget", "kein budget", "kostenlos für dich", "only the product")),
    ("Sehr kurze Frist", ("asap", "heute noch", "within 24", "innerhalb von 24", "tomorrow",
                          "bis morgen")),
)  # fmt: skip
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _has(text: str, words: tuple[str, ...]) -> list[str]:
    return [w for w in words if re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", text)]


def classify(text: str) -> tuple[str, list[str]]:
    """Category and warning flags (German) of an inquiry."""
    t = fold(text)
    flags = [label for label, words in _FLAGS if _has(t, words)]
    spam = _has(t, _SPAM)
    sponsor, product, aff = _has(t, _SPONSOR), _has(t, _PRODUCT), _has(t, _AFFILIATE)
    if spam and not sponsor:
        return "spam", flags
    if "Vorabzahlung verlangt" in flags:
        return "spam", flags
    if aff and not any(w in sponsor for w in ("paid", "bezahlt", "budget", "fee", "honorar")):
        return "affiliate", flags
    if product and not sponsor:
        return "product_test", flags
    if sponsor:
        return "sponsoring", flags
    if product:
        return "product_test", flags
    return "other", flags


def brand_of(sender: str, body: str) -> tuple[str, str | None]:
    name, address = parseaddr(sender or "")
    if not address or "@" not in address:
        found = _EMAIL.search(body or "")
        address = found.group(0) if found else ""
    domain = address.split("@", 1)[1].lower() if "@" in address else ""
    generic = {
        "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "gmx.de", "gmx.net",
        "web.de", "yahoo.com", "icloud.com", "t-online.de", "proton.me", "protonmail.com",
    }  # fmt: skip
    if domain and domain not in generic:
        brand = domain.split(".")[-2].replace("-", " ").title()
    else:
        brand = name.strip() or (address.split("@")[0] if address else "Unbekannt")
    return brand[:200], (address.lower() or None)


def best_project(session: Session, text: str) -> tuple[ContentProject | None, int]:
    words = campaign_fit.words(text)
    best: tuple[ContentProject | None, int] = (None, 0)
    for project in session.scalars(
        select(ContentProject)
        .where(ContentProject.status == ContentProjectStatus.ACTIVE)
        .order_by(ContentProject.priority, ContentProject.id)
    ):
        area = campaign_fit.words(
            " ".join([project.name, project.slug.replace("-", " "), project.description or "",
                      project.audience or "", " ".join(str(s) for s in project.subtopics or [])])
        )  # fmt: skip
        score = min(100, 25 * len(words & area))
        if score > best[1] or best[0] is None:
            best = (project, score)
    return best


def _money(value: Decimal) -> Decimal:
    """Round to a price that reads well: 5 € steps below 200 €, 10 € above."""
    step = Decimal("5") if value < 200 else Decimal("10")
    return ((value / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step).quantize(
        Decimal("0.01")
    )


@dataclass(frozen=True)
class Price:
    per_post: Decimal
    low: Decimal
    high: Decimal
    bundle: Decimal
    basis: dict[str, Any]


def suggest_price(session: Session, project_id: int | None) -> Price:
    channels = (
        list(session.scalars(select(Channel.id).where(Channel.content_project_id == project_id)))
        if project_id
        else []
    )
    median = campaign_fit.median_views(session, channels)
    views = median or 0
    low, typical, high = (max(MIN_PRICE, Decimal(views) / 1000 * c) for c in CPM_EUR)
    per_post = _money(typical)
    bundle = _money(per_post * BUNDLE_POSTS * (1 - BUNDLE_DISCOUNT))
    basis = {
        "median_views": median,
        "channels": len(channels),
        "cpm_eur": [float(c) for c in CPM_EUR],
        "min_price": float(MIN_PRICE),
        "bundle_posts": BUNDLE_POSTS,
        "bundle_discount": float(BUNDLE_DISCOUNT),
        "note": (
            "Mindestpreis, weil noch keine Aufrufzahlen vorliegen"
            if median is None
            else f"Median {median} Aufrufe je Beitrag × {CPM_EUR[1]} € je 1.000"
        ),
    }
    return Price(per_post, _money(low), _money(high), bundle, basis)


# --- drafts ---------------------------------------------------------------------------

STYLE = (
    "You write a reply to a brand that asked a small video channel for a cooperation. "
    "Write like the real person behind the channel: friendly, short, concrete, no hype, "
    "no corporate phrases. Rules:\n"
    "- Same language as the inquiry. 80 to 160 words. Plain text, no Markdown.\n"
    "- Thank them in one short sentence, show you read what they want.\n"
    "- Give the price exactly as given, as a starting point, and what it includes.\n"
    "- Say that the post is clearly marked as advertising (Anzeige / ad).\n"
    "- Ask for what is missing: product details, timing, usage rights, approval process.\n"
    "- Never promise results (views, sales). Never agree to anything final.\n"
    "- Do not invent numbers other than those given. End with the channel name."
)


def template(inq: SponsorInquiry, price: Price, channel_name: str) -> str:
    p, b = _fmt(price.per_post), _fmt(price.bundle)
    if inq.language == Language.EN:
        if inq.category == "affiliate":
            offer = (
                "Commission-only deals do not fit right now. For a paid short my rate starts "
                f"at {p} EUR per video, or {b} EUR for {BUNDLE_POSTS} videos."
            )
        elif inq.category == "product_test":
            offer = (
                "I only show products I have really tried. A short with the product starts at "
                f"{p} EUR, or {b} EUR for {BUNDLE_POSTS} videos; the product alone is not enough "
                "for a dedicated video."
            )
        else:
            offer = (
                f"For one sponsored short my rate starts at {p} EUR, or {b} EUR for "
                f"{BUNDLE_POSTS} videos. That covers idea, edit and posting on the channel."
            )
        return (
            f"Hi,\n\nthanks for reaching out about {inq.brand}. {offer} Every sponsored post is "
            "clearly marked as an ad.\n\nCould you send me a few details: what exactly you "
            "would like to show, your timing, and whether you want to reuse the video "
            "yourselves (usage rights are priced separately)?\n\nBest,\n"
            f"{channel_name}"
        )
    if inq.category == "affiliate":
        offer = (
            "Reine Provisionsdeals passen gerade nicht. Für ein bezahltes Video liege ich bei "
            f"{p} € pro Short, {BUNDLE_POSTS} Videos zusammen {b} €."
        )
    elif inq.category == "product_test":
        offer = (
            "Ich zeige nur, was ich wirklich ausprobiert habe. Ein eigenes Video mit dem "
            f"Produkt startet bei {p} €, {BUNDLE_POSTS} Videos zusammen {b} €. Nur das "
            "Produkt reicht für ein eigenes Video leider nicht."
        )
    else:
        offer = (
            f"Für ein gesponsertes Short liege ich bei {p} €, für {BUNDLE_POSTS} Videos "
            f"zusammen bei {b} €. Darin sind Idee, Schnitt und Veröffentlichung enthalten."
        )
    return (
        f"Hallo,\n\ndanke für eure Nachricht zu {inq.brand}. {offer} Jeder Beitrag wird "
        "deutlich als Anzeige gekennzeichnet.\n\nSchickt mir gern noch ein paar Details: "
        "was genau gezeigt werden soll, euren Zeitplan und ob ihr das Video selbst weiter "
        "nutzen möchtet (Nutzungsrechte rechne ich extra).\n\nViele Grüße\n"
        f"{channel_name}"
    )


def _fmt(value: Decimal) -> str:
    return f"{value:,.0f}".replace(",", ".")


def _clean(text: str) -> str | None:
    text = re.sub(r"[*#`]+", "", text or "").strip()
    if len(text) < 40 or len(text) > 2500:
        return None
    return text


def draft(
    session: Session, settings: Settings, inq: SponsorInquiry, price: Price, user_id: int | None
) -> tuple[str, str]:
    """Reply draft and its source (``template``, ``mock`` or the provider)."""
    channel_name = _signature(session, inq)
    fallback = template(inq, price, channel_name)
    if inq.category == "spam":
        return "", "none"
    lang_name = "German" if inq.language == Language.DE else "English"
    prompt = (
        f"Inquiry from {inq.brand} (category: {CATEGORY_LABELS[inq.category]}).\n"
        f"Subject: {inq.subject or '-'}\n---\n{inq.body[:4000]}\n---\n"
        f"Reply language: {lang_name}. Channel name: {channel_name}.\n"
        f"Price per short (starting point): {_fmt(price.per_post)} EUR; "
        f"{BUNDLE_POSTS} shorts together: {_fmt(price.bundle)} EUR.\n"
        "Warnings to keep in mind (do not mention them literally): "
        + (", ".join(inq.flags) if inq.flags else "none")
    )
    try:
        result = ai.generate(
            session,
            settings,
            ai.AIRequest(
                purpose="sponsor_reply",
                tier="text",
                messages=[ai.AIMessage("user", prompt)],
                system=STYLE,
                max_tokens=500,
                mock=lambda _req: fallback,
                content_project_id=inq.content_project_id,
                user_id=user_id,
                meta={"sponsor_inquiry_id": inq.id},
            ),
        )
    except ai.AIError as exc:
        log.info("sponsor inquiry %s: template draft (%s)", inq.id, exc.code)
        return fallback, "template"
    text = _clean(result.text)
    if text is None or _fmt(price.per_post) not in text:
        return fallback, "template"
    return text, "mock" if result.provider == ai.MOCK else result.provider


def _signature(session: Session, inq: SponsorInquiry) -> str:
    if inq.content_project_id is None:
        return "Kanalfabrik"
    channel = session.scalar(
        select(Channel)
        .where(
            Channel.content_project_id == inq.content_project_id,
            Channel.language == inq.language,
        )
        .order_by(Channel.id)
    )
    project = session.get(ContentProject, inq.content_project_id)
    return channel.name if channel else (project.name if project else "Kanalfabrik")


class SponsorError(ValueError):
    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def add(
    session: Session,
    settings: Settings,
    body: str,
    sender: str = "",
    subject: str | None = None,
    project_id: int | None = None,
    user_id: int | None = None,
    now: datetime | None = None,
) -> SponsorInquiry:
    body = (body or "").strip()
    if len(body) < 20:
        raise SponsorError("Bitte den Text der Anfrage einfügen")
    text = f"{subject or ''}\n{body}"
    category, flags = classify(text)
    brand, email = brand_of(sender, body)
    if project_id is not None:
        project = session.get(ContentProject, project_id)
        if project is None:
            raise SponsorError("Themenbereich nicht gefunden", 404)
        fit = 100
    else:
        project, fit = best_project(session, text)
    inq = SponsorInquiry(
        content_project_id=project.id if project else None,
        brand=brand,
        contact_email=email,
        subject=(subject or "").strip()[:300] or None,
        body=body[:20000],
        received_at=now or datetime.now(UTC),
        language=language_of(text, Language.DE),
        category=category,
        flags=flags,
        fit_score=fit,
        status="archived" if category == "spam" else "new",
    )
    session.add(inq)
    session.flush()
    refresh(session, settings, inq, user_id)
    return inq


def refresh(
    session: Session, settings: Settings, inq: SponsorInquiry, user_id: int | None = None
) -> SponsorInquiry:
    """Price and draft again (after the topic area changed or on request)."""
    price = suggest_price(session, inq.content_project_id)
    inq.price_eur = price.per_post
    inq.price_basis = {
        **price.basis,
        "low": float(price.low),
        "high": float(price.high),
        "bundle": float(price.bundle),
    }
    inq.draft, inq.draft_source = draft(session, settings, inq, price, user_id)
    session.flush()
    return inq
