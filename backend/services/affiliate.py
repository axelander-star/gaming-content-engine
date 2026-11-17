"""Affiliate links with a clear ad label (Ausbau A8).

German law (§ 5a Abs. 4 UWG, § 6 DDG) asks that commercial content is recognisable
at first sight. So:

* on the bio page every affiliate link carries the label "Anzeige" (English "Ad")
  and the page explains what an affiliate link is;
* a link only goes into post texts when the operator switches ``in_posts`` on;
  then the post text *starts* with "Anzeige: …" and the variant is marked as
  commercial (``publish_options["commercial_content"]``), so the approval center
  reminds to switch on the platform's own label (TikTok "Markeninhalt",
  YouTube "Bezahlte Werbung", Instagram "Bezahlte Partnerschaft") in the app.
  The link itself sits on the bio page: links in Shorts/TikTok/Reels texts are
  not clickable.

Clicks are counted by the public redirect ``/go/<id>`` (no cookie, no IP).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.enums import Language
from models.channels import Channel
from models.marketing import AffiliateLink, BioPage
from models.production import Variant

LABEL = {Language.DE: "Anzeige", Language.EN: "Ad"}
EDITABLE = ("title", "url", "program", "language", "keywords", "in_posts", "active", "note")


class AffiliateError(ValueError):
    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def check_url(url: str) -> str:
    url = (url or "").strip()
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.netloc or " " in url:
        raise AffiliateError("Der Link muss mit https:// beginnen")
    if len(url) > 1000:
        raise AffiliateError("Der Link ist zu lang")
    return url


def _keywords(values: Any) -> list[str]:
    out: list[str] = []
    for v in values or []:
        word = " ".join(str(v).split()).strip()[:60]
        if word and word.lower() not in {w.lower() for w in out}:
            out.append(word)
    return out[:20]


def apply_fields(link: AffiliateLink, data: dict[str, Any]) -> None:
    for key in EDITABLE:
        if key not in data:
            continue
        value = data[key]
        if key == "url":
            value = check_url(value)
        elif key == "keywords":
            value = _keywords(value)
        elif key == "title":
            value = " ".join(str(value or "").split())[:120]
            if not value:
                raise AffiliateError("Titel fehlt")
        elif key == "language" and value is not None:
            value = Language(value)
        setattr(link, key, value)


def links_for(session: Session, project_id: int, language: Language) -> list[AffiliateLink]:
    return list(
        session.scalars(
            select(AffiliateLink)
            .where(
                AffiliateLink.content_project_id == project_id,
                AffiliateLink.active.is_(True),
                (AffiliateLink.language.is_(None)) | (AffiliateLink.language == language),
            )
            .order_by(AffiliateLink.id)
        )
    )


def match(session: Session, variant: Variant, game: str | None = None) -> AffiliateLink | None:
    """The link a post may mention: active, ``in_posts``, a keyword in title or game."""
    text = " ".join(filter(None, [variant.title, variant.description, game])).lower()
    for link in links_for(session, variant.content_project_id, variant.language):
        if link.in_posts and any(k.lower() in text for k in link.keywords or []):
            return link
    return None


def disclosure(language: Language, link: AffiliateLink) -> str:
    if language == Language.EN:
        return f"{LABEL[language]}: {link.title} – link in bio"
    return f"{LABEL[language]}: {link.title} – Link in meiner Bio"


def apply_texts(session: Session, variant: Variant, game: str | None = None) -> bool:
    """Put the ad line at the start of the post text (idempotent).

    Only when the channel's bio page is switched on: without it the hint would
    point nowhere."""
    if (variant.concept or {}).get("affiliate_link_id"):
        return False
    channel = session.get(Channel, variant.channel_id)
    page = session.scalar(select(BioPage).where(BioPage.channel_id == variant.channel_id))
    if channel is None or page is None or not page.enabled:
        return False
    link = match(session, variant, game)
    if link is None:
        return False
    line = disclosure(variant.language, link)
    variant.description = f"{line}\n{(variant.description or '').strip()}".strip()
    variant.concept = {**(variant.concept or {}), "affiliate_link_id": link.id}
    variant.publish_options = {**(variant.publish_options or {}), "commercial_content": True}
    return True


def text_problem(variant: Variant) -> str | None:
    """A post that mentions an affiliate link must start with the ad label."""
    if not (variant.concept or {}).get("affiliate_link_id"):
        return None
    label = LABEL.get(variant.language, "Anzeige")
    if not (variant.description or "").lstrip().startswith(label):
        return f"Werbehinweis „{label}“ fehlt am Anfang der Beschreibung"
    return None


def strip_for_channel(session: Session, variant: Variant, channel_id: int) -> None:
    """A copy for another channel keeps the ad line only if that bio page is on."""
    link_id = (variant.concept or {}).get("affiliate_link_id")
    if not link_id:
        return
    page = session.scalar(select(BioPage).where(BioPage.channel_id == channel_id))
    if page is not None and page.enabled:
        return
    lines = (variant.description or "").split("\n")
    label = LABEL.get(variant.language, "Anzeige")
    if lines and lines[0].startswith(f"{label}:"):
        variant.description = "\n".join(lines[1:]).strip()
    variant.concept = {k: v for k, v in (variant.concept or {}).items() if k != "affiliate_link_id"}
    variant.publish_options = {
        k: v for k, v in (variant.publish_options or {}).items() if k != "commercial_content"
    }
