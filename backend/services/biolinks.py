"""Public bio-link page per channel (Ausbau A8).

The page is what the "link in bio" of a profile points to. It shows

* the other profiles of the topic area in the same language,
* the latest real videos of the channel (no test posts),
* the operator's own links and the affiliate links, each labelled "Anzeige"/"Ad",
* the newsletter form (double opt-in, see :mod:`services.newsletter`),
* a link to imprint and privacy policy (``LEGAL_PAGE_URL``).

Pages are created for every channel but stay off until the operator switches
them on. They are rendered on the server as plain HTML without scripts,
cookies or external resources, so no consent banner is needed.
"""

# ruff: noqa: E501  (inline HTML and CSS of the public page)
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import ChannelSetupStatus, Language, PlatformCode
from models.channel_setup import ChannelSetupTask
from models.channels import Channel
from models.marketing import AffiliateLink, BioPage
from models.production import Variant
from models.publishing import Post
from services import affiliate
from services.projects import slugify

EDITABLE = ("slug", "enabled", "headline", "intro", "links", "show_videos", "newsletter_enabled")
MAX_LINKS = 12
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,58}[a-z0-9])$")
RESERVED = {"go", "n", "l", "api", "admin", "static", "public"}
PROFILE_URL = {
    PlatformCode.YOUTUBE: "https://www.youtube.com/@{h}",
    PlatformCode.TIKTOK: "https://www.tiktok.com/@{h}",
    PlatformCode.INSTAGRAM: "https://www.instagram.com/{h}/",
    PlatformCode.FACEBOOK: "https://www.facebook.com/{h}",
}


class BioError(ValueError):
    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _handle(session: Session, channel: Channel) -> str | None:
    return session.scalar(
        select(ChannelSetupTask.handle).where(
            ChannelSetupTask.channel_id == channel.id,
            ChannelSetupTask.status == ChannelSetupStatus.DONE,
        )
    )


def _free_slug(session: Session, base: str) -> str:
    base = slugify(base)[:50].strip("-") or "kanal"
    if base in RESERVED or len(base) < 3:
        base = f"kanal-{base}"
    slug, n = base, 2
    while session.scalar(select(BioPage.id).where(BioPage.slug == slug)) is not None:
        slug, n = f"{base}-{n}", n + 1
    return slug


def ensure_pages(session: Session) -> list[BioPage]:
    """A (switched off) page for every channel that has none yet."""
    have = set(session.scalars(select(BioPage.channel_id)))
    made = []
    for channel in session.scalars(select(Channel).order_by(Channel.id)):
        if channel.id in have:
            continue
        page = BioPage(
            channel_id=channel.id,
            slug=_free_slug(session, _handle(session, channel) or channel.name),
            headline=channel.name[:120],
            intro=(channel.description or None),
        )
        session.add(page)
        session.flush()
        made.append(page)
    return made


def _clean_links(values: Any) -> list[dict[str, str]]:
    out = []
    for item in values or []:
        if not isinstance(item, dict):
            raise BioError("Link braucht Titel und Adresse")
        title = " ".join(str(item.get("title") or "").split())[:80]
        if not title:
            raise BioError("Link ohne Titel")
        try:
            url = affiliate.check_url(str(item.get("url") or ""))
        except affiliate.AffiliateError as exc:
            raise BioError(f"{title}: {exc.message}") from exc
        out.append({"title": title, "url": url})
    if len(out) > MAX_LINKS:
        raise BioError(f"Höchstens {MAX_LINKS} eigene Links")
    return out


def update(session: Session, page: BioPage, data: dict[str, Any]) -> BioPage:
    for key in EDITABLE:
        if key not in data or (data[key] is None and key in ("slug", "headline")):
            continue
        value = data[key]
        if key == "slug":
            value = str(value).strip().lower()
            if not SLUG_RE.match(value) or value in RESERVED:
                raise BioError("Adresse: 3–60 Zeichen, nur a–z, 0–9 und Bindestrich")
            taken = session.scalar(
                select(BioPage.id).where(BioPage.slug == value, BioPage.id != page.id)
            )
            if taken is not None:
                raise BioError("Diese Adresse ist schon vergeben", 409)
        elif key == "headline":
            value = " ".join(str(value).split())[:120]
            if not value:
                raise BioError("Überschrift fehlt")
        elif key == "intro":
            value = (str(value).strip()[:600] or None) if value is not None else None
        elif key == "links":
            value = _clean_links(value)
        setattr(page, key, value)
    session.flush()
    return page


def public_url(settings: Settings, page: BioPage) -> str | None:
    base = settings.public_links_base_url.rstrip("/")
    return f"{base}/l/{page.slug}" if base else None


@dataclass
class PageData:
    page: BioPage
    channel: Channel
    language: Language
    profiles: list[dict[str, str]] = field(default_factory=list)
    videos: list[dict[str, str]] = field(default_factory=list)
    affiliates: list[AffiliateLink] = field(default_factory=list)


def collect(session: Session, page: BioPage) -> PageData:
    channel = session.get(Channel, page.channel_id)
    assert channel is not None
    data = PageData(page, channel, channel.language)
    siblings = session.scalars(
        select(Channel)
        .where(
            Channel.content_project_id == channel.content_project_id,
            Channel.language == channel.language,
        )
        .order_by(Channel.id)
    )
    for c in siblings:
        handle = _handle(session, c)
        template = PROFILE_URL.get(c.platform.code)
        if handle and template:
            data.profiles.append({"title": c.platform.name, "url": template.format(h=handle)})
    if page.show_videos:
        rows = session.execute(
            select(Post.url, Variant.title)
            .join(Variant, Variant.id == Post.variant_id)
            .where(
                Post.channel_id == channel.id,
                Post.is_mock.is_(False),
                Post.url.is_not(None),
                Post.published_at.is_not(None),
            )
            .order_by(Post.published_at.desc())
            .limit(3)
        ).all()
        data.videos = [{"title": t or "Video", "url": u} for u, t in rows if u]
    data.affiliates = affiliate.links_for(session, channel.content_project_id, channel.language)
    return data


# --- HTML ------------------------------------------------------------------------------

TEXT = {
    Language.DE: {
        "profiles": "Hier findest du mich auch",
        "videos": "Neueste Videos",
        "links": "Links",
        "ad_note": (
            "Mit „Anzeige“ markierte Links sind Affiliate-Links. Kaufst du darüber, "
            "bekomme ich eine kleine Provision. Für dich ändert sich am Preis nichts."
        ),
        "news_title": "Newsletter",
        "news_text": "Die besten Clips der Woche, einmal pro Woche. Abmelden geht jederzeit.",
        "email": "E-Mail-Adresse",
        "consent": (
            "Ja, schickt mir den Newsletter an diese Adresse. Ich kann ihn jederzeit "
            "über den Link in jeder Mail abbestellen."
        ),
        "submit": "Anmelden",
        "legal": "Impressum und Datenschutz",
    },
    Language.EN: {
        "profiles": "Find me here too",
        "videos": "Latest videos",
        "links": "Links",
        "ad_note": (
            "Links marked “Ad” are affiliate links. If you buy through them I get a "
            "small commission. The price stays the same for you."
        ),
        "news_title": "Newsletter",
        "news_text": "The best clips of the week, once a week. Unsubscribe any time.",
        "email": "Email address",
        "consent": (
            "Yes, send me the newsletter at this address. I can unsubscribe any time "
            "with the link in every email."
        ),
        "submit": "Sign up",
        "legal": "Imprint and privacy",
    },
}

STYLE = """
:root{color-scheme:light dark;--bg:#f6f7f9;--card:#fff;--fg:#16181d;--muted:#5b6170;
--line:#dfe2e8;--accent:#3b5bdb;--ad:#8a5a00;--adbg:#fff3d6}
@media (prefers-color-scheme:dark){:root{--bg:#111318;--card:#1b1e25;--fg:#eceef3;
--muted:#a3a9b6;--line:#2c313b;--accent:#8ea2ff;--ad:#ffd38a;--adbg:#3a2c10}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:520px;margin:0 auto;padding:32px 16px 48px}
.avatar{width:72px;height:72px;border-radius:50%;background:var(--accent);color:#fff;
display:grid;place-items:center;font-size:32px;font-weight:700;margin:0 auto 12px}
h1{font-size:22px;text-align:center;margin:0 0 6px}p.intro{text-align:center;color:var(--muted);margin:0 0 24px}
h2{font-size:14px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin:28px 0 10px}
a.btn{display:flex;justify-content:space-between;gap:8px;align-items:center;padding:14px 16px;
margin:0 0 10px;background:var(--card);border:1px solid var(--line);border-radius:12px;
color:var(--fg);text-decoration:none;font-weight:600}a.btn:hover{border-color:var(--accent)}
.tag{font-size:12px;font-weight:700;color:var(--ad);background:var(--adbg);padding:2px 8px;border-radius:99px;white-space:nowrap}
.note{font-size:13px;color:var(--muted)}
form{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
input[type=email]{width:100%;padding:12px;border:1px solid var(--line);border-radius:8px;
background:var(--bg);color:var(--fg);font-size:16px;margin:6px 0 10px}
label.c{display:flex;gap:8px;font-size:14px;color:var(--muted);margin-bottom:12px}
button{width:100%;padding:12px;border:0;border-radius:8px;background:var(--accent);color:#fff;font-weight:700;font-size:16px}
.hp{position:absolute;left:-9999px}footer{margin-top:32px;text-align:center;font-size:13px}
footer a{color:var(--muted)}.msg{text-align:center;padding:48px 16px}
"""


def _e(text: str) -> str:
    return html.escape(text, quote=True)


def document(title: str, body: str, language: Language) -> str:
    return (
        f'<!doctype html><html lang="{language.value}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex">'
        f"<title>{_e(title)}</title><style>{STYLE}</style></head>"
        f"<body><main>{body}</main></body></html>"
    )


def render(data: PageData, settings: Settings, prefix: str, notice: str | None = None) -> str:
    t = TEXT[data.language]
    page = data.page
    parts = [
        f'<div class="avatar" aria-hidden="true">{_e(page.headline[:1].upper())}</div>',
        f"<h1>{_e(page.headline)}</h1>",
    ]
    if page.intro:
        parts.append(f'<p class="intro">{_e(page.intro)}</p>')
    if notice:
        parts.append(f'<p class="intro"><strong>{_e(notice)}</strong></p>')

    def btn(title: str, url: str, rel: str = "noopener", tag: str = "") -> str:
        badge = f'<span class="tag">{_e(tag)}</span>' if tag else ""
        return f'<a class="btn" href="{_e(url)}" rel="{rel}"><span>{_e(title)}</span>{badge}</a>'

    profiles = [p for p in data.profiles if p["title"] != data.channel.platform.name]
    if profiles:
        parts.append(f"<h2>{t['profiles']}</h2>")
        parts += [btn(p["title"], p["url"], "me noopener") for p in profiles]
    if data.videos:
        parts.append(f"<h2>{t['videos']}</h2>")
        parts += [btn(v["title"], v["url"]) for v in data.videos]
    if page.links or data.affiliates:
        parts.append(f"<h2>{t['links']}</h2>")
        parts += [btn(link["title"], link["url"]) for link in page.links or []]
        label = affiliate.LABEL[data.language]
        parts += [
            btn(
                a.title,
                f"{prefix}/go/{a.id}?c={data.channel.id}",
                "sponsored nofollow noopener",
                label,
            )
            for a in data.affiliates
        ]
        if data.affiliates:
            parts.append(f'<p class="note">{_e(t["ad_note"])}</p>')
    if page.newsletter_enabled:
        parts.append(f"<h2>{t['news_title']}</h2>")
        parts.append(
            f'<form method="post" action="{prefix}/l/{_e(page.slug)}/newsletter">'
            f'<p class="note" style="margin-top:0">{_e(t["news_text"])}</p>'
            f'<label for="email">{_e(t["email"])}</label>'
            '<input id="email" type="email" name="email" required maxlength="254" autocomplete="email">'
            '<label class="hp" aria-hidden="true">Website<input name="website" tabindex="-1" autocomplete="off"></label>'
            f'<label class="c"><input type="checkbox" name="consent" value="yes" required>{_e(t["consent"])}</label>'
            f'<button type="submit">{_e(t["submit"])}</button></form>'
        )
    if settings.legal_page_url:
        parts.append(
            f'<footer><a href="{_e(settings.legal_page_url)}">{_e(t["legal"])}</a></footer>'
        )
    return document(page.headline, "".join(parts), data.language)


def message(title: str, text: str, language: Language, form: str = "") -> str:
    return document(
        title, f'<div class="msg"><h1>{_e(title)}</h1><p>{_e(text)}</p>{form}</div>', language
    )
