"""Channel assistant: find missing channels of a topic area and prepare them.

For every topic area the engine wants one channel per platform (YouTube, TikTok,
Instagram) and language. For each combination without a channel it prepares a
:class:`~models.channel_setup.ChannelSetupTask` with everything the operator
needs to create the account by hand:

* display name, handle and alternative handles (platform rules applied);
* bio in the channel's language, within the platform's length limit;
* profile picture and (YouTube) banner, drawn locally (``services.branding``);
* a forwarding e-mail address for TikTok and Instagram (``services.mail_alias``);
* the sign-up link and the steps to follow, phone/captcha included.

The engine never creates platform accounts itself: automated sign-ups break the
terms of Google, TikTok and Meta and would put every channel at risk.

Handle availability is checked only where an official API exists (YouTube Data
API ``channels.list forHandle``, 1 quota unit, with ``YOUTUBE_API_KEY`` and
``TREND_SOURCES_MODE=live``). TikTok and Instagram have no such API, so the
operator gets alternatives and sees availability during sign-up.
"""

from __future__ import annotations

import io
import json
import logging
import re
import secrets
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import (
    ChannelAuthStatus,
    ChannelSetupStatus,
    ContentProjectStatus,
    Language,
    MailAliasStatus,
    PlatformCode,
)
from models.channel_setup import ChannelSetupTask
from models.channels import Channel, Platform
from models.marketing import OutgoingMail
from models.projects import ContentProject
from services import ai, audit, branding, image_ai, mail_alias, mailer, name_research, storage
from services.name_research import MarketContext, norm_name
from services.queue import get_redis

log = logging.getLogger(__name__)

TARGET_PLATFORMS = (PlatformCode.YOUTUBE, PlatformCode.TIKTOK, PlatformCode.INSTAGRAM)


class SetupError(ValueError):
    """An action that is not allowed (German message for the dashboard)."""


@dataclass(frozen=True)
class PlatformRules:
    label: str
    handle_min: int
    handle_max: int
    handle_chars: str  # allowed characters besides a-z and 0-9
    name_max: int
    bio_max: int
    needs_email: bool
    banner: bool
    signup_url: str
    steps: tuple[str, ...]


RULES: dict[PlatformCode, PlatformRules] = {
    PlatformCode.YOUTUBE: PlatformRules(
        label="YouTube",
        handle_min=3,
        handle_max=30,
        handle_chars="._-",
        name_max=100,
        bio_max=1000,
        needs_email=False,
        banner=True,
        signup_url="https://www.youtube.com/channel_switcher",
        steps=(
            "Mit dem geschäftlichen Google-Konto anmelden (nicht dem privaten).",
            "Auf „Kanal erstellen“ klicken und den Kanalnamen eintragen. So entsteht ein "
            "Brand-Kanal unter dem Geschäftskonto, ein neues Google-Konto ist nicht nötig.",
            "In YouTube Studio unter „Anpassung“ den Handle, die Beschreibung, das "
            "Profilbild und das Banner eintragen.",
            "Falls YouTube eine Telefonbestätigung verlangt, diese selbst durchführen.",
            "Zurück im Dashboard auf „Kanal ist angelegt“ und danach auf „Verbinden“ klicken.",
        ),
    ),
    PlatformCode.TIKTOK: PlatformRules(
        label="TikTok",
        handle_min=2,
        handle_max=24,
        handle_chars="._",
        name_max=30,
        bio_max=80,
        needs_email=True,
        banner=False,
        signup_url="https://www.tiktok.com/signup",
        steps=(
            "In einem privaten Browserfenster öffnen, damit kein anderes TikTok-Konto "
            "angemeldet ist.",
            "„Telefon oder E-Mail verwenden“ wählen, dann „Mit E-Mail registrieren“ und "
            "die E-Mail-Adresse von hier eintragen.",
            "Den Bestätigungscode aus deinem Postfach eintragen (die Adresse leitet dorthin "
            "weiter) und Captcha bzw. Telefon selbst bestätigen.",
            "Benutzernamen, Namen, Bio und Profilbild von hier übernehmen.",
            "Zurück im Dashboard auf „Kanal ist angelegt“ und danach auf „Verbinden“ klicken.",
        ),
    ),
    PlatformCode.INSTAGRAM: PlatformRules(
        label="Instagram",
        handle_min=1,
        handle_max=30,
        handle_chars="._",
        name_max=30,
        bio_max=150,
        needs_email=True,
        banner=False,
        signup_url="https://www.instagram.com/accounts/emailsignup/",
        steps=(
            "In einem privaten Browserfenster öffnen, damit kein anderes Instagram-Konto "
            "angemeldet ist.",
            "Mit der E-Mail-Adresse von hier registrieren und den Code aus deinem Postfach "
            "eintragen; Captcha bzw. Telefon selbst bestätigen.",
            "Benutzernamen, Namen, Bio und Profilbild von hier übernehmen.",
            "Unter Einstellungen „Kontotyp und Tools“ auf ein professionelles Konto "
            "(Creator) umstellen. Ohne diesen Schritt kann die Engine nicht posten.",
            "Zurück im Dashboard auf „Kanal ist angelegt“ und danach auf „Verbinden“ klicken.",
        ),
    ),
}

LANGUAGE_NAMES = {Language.DE: "Deutsch", Language.EN: "Englisch"}

# --- coverage --------------------------------------------------------------------------


@dataclass
class Slot:
    platform: PlatformCode
    language: Language
    #: "connected", "added" (channel exists, not connected), "placeholder" (seed
    #: channel without a real account), "prepared" (open task) or "missing".
    state: str
    channel_id: int | None = None
    channel_name: str | None = None
    task_id: int | None = None


@dataclass
class Coverage:
    project: ContentProject
    slots: list[Slot] = field(default_factory=list)

    @property
    def missing(self) -> list[Slot]:
        """Slots without a real account: nothing at all, or only a placeholder."""
        return [s for s in self.slots if s.state in ("missing", "placeholder")]


_CONNECTED = (ChannelAuthStatus.AUTHORIZED, ChannelAuthStatus.CONNECTED_RESTRICTED)


def is_placeholder(channel: Channel) -> bool:
    """A seed channel ("YouTube Shorts DE" …) that has no real account behind it yet."""
    return (
        bool((channel.strategy or {}).get("placeholder"))
        and channel.auth_status not in _CONNECTED
        and not channel.external_channel_id
    )


def languages_of(project: ContentProject) -> list[Language]:
    langs = [Language(c) for c in project.languages or [] if c in Language._value2member_map_]
    return langs or [Language.DE]


def coverage(session: Session, project: ContentProject) -> Coverage:
    channels = session.execute(
        select(Channel, Platform.code)
        .join(Platform, Platform.id == Channel.platform_id)
        .where(Channel.content_project_id == project.id)
        .order_by(Channel.id)
    ).all()
    tasks = session.scalars(
        select(ChannelSetupTask).where(
            ChannelSetupTask.content_project_id == project.id,
            ChannelSetupTask.status == ChannelSetupStatus.OPEN,
        )
    ).all()
    result = Coverage(project)
    for plat in TARGET_PLATFORMS:
        for lang in languages_of(project):
            mine = [c for c, code in channels if code == plat and c.language == lang]
            connected = [c for c in mine if c.auth_status in _CONNECTED]
            task = next((t for t in tasks if t.platform == plat and t.language == lang), None)
            if connected:
                c = connected[0]
                result.slots.append(Slot(plat, lang, "connected", c.id, c.name))
            elif task:
                # an open task, possibly for an existing placeholder channel
                result.slots.append(Slot(plat, lang, "prepared", task.channel_id, task_id=task.id))
            elif mine:
                real = [c for c in mine if not is_placeholder(c)]
                c = (real or mine)[0]
                state = "added" if real else "placeholder"
                result.slots.append(Slot(plat, lang, state, c.id, c.name))
            else:
                result.slots.append(Slot(plat, lang, "missing"))
    return result


# --- names, handles, bios --------------------------------------------------------------


def _ascii(text: str) -> str:
    text = text.replace("ß", "ss").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    text = text.replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue")
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def normalize_handle(raw: str, platform: PlatformCode) -> str:
    """Lower-case handle with only the characters the platform allows."""
    rules = RULES[platform]
    text = _ascii(raw).lower().lstrip("@")
    allowed = re.escape(rules.handle_chars)
    text = re.sub(rf"[^a-z0-9{allowed}]+", "_" if "_" in rules.handle_chars else "", text)
    text = re.sub(r"([._-])[._-]+", r"\1", text).strip("._-")
    text = text[: rules.handle_max].rstrip("._-")
    if len(text) < rules.handle_min:
        text = (text + "kanal")[: rules.handle_max]
    return text


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,.;:-") + "…"


@dataclass
class Texts:
    display_name: str
    handles: list[str]
    bio: str
    tagline: str
    source: str
    #: further name ideas: ``[{"name": ..., "reason": ...}]``
    options: list[dict[str, str]] = field(default_factory=list)


def _template_options(
    project: ContentProject, language: Language, ctx: MarketContext | None
) -> list[dict[str, str]]:
    """Name ideas from the area's sub-topics and the most frequent topic words (no AI)."""
    topic = project.name.strip()
    suffix = "Kompakt" if language == Language.DE else "Daily"
    out: list[dict[str, str]] = []
    if language == Language.DE:
        for sub in [str(t).strip() for t in project.subtopics or [] if str(t).strip()][:3]:
            out.append({"name": sub, "reason": "Unterthema des Themenbereichs"})
    if ctx is None:
        return out
    for word, n in ctx.keywords[:3]:
        for name in (f"{word} {suffix}", f"{topic} & {word}"):
            out.append({"name": name, "reason": f"„{word}“ kam zuletzt {n}× in Meldungen vor"})
    return out


def template_texts(
    project: ContentProject,
    platform: PlatformCode,
    language: Language,
    ctx: MarketContext | None = None,
) -> Texts:
    """Texts without AI: simple, honest and editable in the dashboard."""
    topic = project.name.strip()
    base = _ascii(topic).lower().replace(" ", "")
    subtopics = [str(t).strip() for t in project.subtopics or [] if str(t).strip()]
    if language == Language.DE:
        name = f"{topic} Kompakt"
        tagline = f"{topic} in unter 60 Sekunden"
        bio = (
            f"{topic} kurz und ehrlich erklärt. Jede Woche neue Shorts mit Tipps, Trends "
            f"und Aha-Momenten."
        )
        if subtopics:  # the area's own words beat a generic sentence
            tagline = _clip(f"{subtopics[0]} in unter 60 Sekunden", 45)
            bio = _clip(
                f"{', '.join(subtopics[:3])}: kurz, verblüffend und ehrlich. "
                "Jeden Tag neue Shorts.",
                160,
            )
        handles = [f"{base}kompakt", f"{base}.kurz", f"{base}_de"]
    else:
        name = f"{topic} Daily"
        tagline = f"{topic} in under 60 seconds"
        bio = f"{topic}, short and honest. New shorts every week with tips, trends and quick facts."
        handles = [f"{base}daily", f"{base}.shorts", f"{base}_en"]
    return Texts(name, handles, bio, tagline, "template", _template_options(project, language, ctx))


SYSTEM = (
    "You are a top social media brand strategist who names new short-video channels. "
    "Names must make people stop scrolling: short (1-3 words), punchy, memorable, easy to "
    "say, with a twist, wordplay, contrast or curiosity gap. Think of channel names that "
    "feel like a brand, not a description; avoid generic patterns such as '<topic> Kompakt', "
    "'<topic> Daily' or 'Facts TV'. No emojis, no hashtags, no clickbait lies. Use the "
    "market data: pick words people actually search for, stand apart from the existing "
    "channels and never copy or imitate their names. Bios open with a hook that triggers "
    "curiosity, then say concretely what the viewer gets and how often; they sound like a "
    "real person with personality, never like marketing ('ultimate', 'unlock'). "
    "Write in the channel language with natural, current wording. Answer with JSON only."
)


def _prompt(
    project: ContentProject,
    platform: PlatformCode,
    language: Language,
    ctx: MarketContext | None = None,
    note: str = "",
) -> str:
    rules = RULES[platform]
    lang = "German" if language == Language.DE else "English"
    subtopics = ", ".join(str(s) for s in project.subtopics or []) or "-"
    return (
        f"Topic area: {project.name}\n"
        f"Description: {project.description or '-'}\n"
        f"Sub-topics: {subtopics}\n"
        f"Audience: {project.audience or '-'}\nTone: {project.tone or '-'}\n"
        f"Platform: {rules.label}. Channel language: {lang} (translate the topic if needed).\n"
        f"Market data:\n{ctx.prompt_block() if ctx else 'No market data yet.'}\n"
        f"Return JSON with keys: display_name (max {rules.name_max} chars), alternatives "
        f"(list of 4 objects with name and reason; reason in German, max 90 chars, naming "
        f"the data it is based on), handles "
        f"(list of 3 handles, {rules.handle_min}-{rules.handle_max} chars, only a-z 0-9 and "
        f"'{rules.handle_chars}'), bio (max {rules.bio_max} chars, max 2 sentences), "
        f"tagline (max 45 chars, for the banner)." + (f"\n{note}" if note else "")
    )


def _parse(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(text[start : end + 1])
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def write_texts(
    session: Session,
    settings: Settings,
    project: ContentProject,
    platform: PlatformCode,
    language: Language,
    user_id: int | None = None,
    ctx: MarketContext | None = None,
    note: str = "",
) -> Texts:
    """Name, handles and bio from the AI (mock in test mode); template if that fails.

    ``note`` is an extra instruction, e.g. which values to replace with new ones."""
    fallback = _drop_taken(template_texts(project, platform, language, ctx), ctx)
    mock = json.dumps(
        {
            "display_name": fallback.display_name,
            "alternatives": fallback.options,
            "handles": fallback.handles,
            "bio": fallback.bio,
            "tagline": fallback.tagline,
        },
        ensure_ascii=False,
    )
    try:
        result = ai.generate(
            session,
            settings,
            ai.AIRequest(
                purpose="channel_setup",
                tier="text",
                messages=[ai.AIMessage("user", _prompt(project, platform, language, ctx, note))],
                system=SYSTEM,
                max_tokens=900,
                mock=lambda _req: mock,
                content_project_id=project.id,
                user_id=user_id,
            ),
        )
    except ai.AIError as exc:
        log.info("channel texts from template (%s)", exc.code)
        return fallback
    data = _parse(result.text)
    name = " ".join(str(data.get("display_name") or "").split())
    raw_handles = data.get("handles")
    handles = (
        [str(h) for h in raw_handles if isinstance(h, str)] if isinstance(raw_handles, list) else []
    )
    bio = " ".join(str(data.get("bio") or "").split())
    tagline = " ".join(str(data.get("tagline") or "").split())
    if not name or not handles or not bio:
        return fallback
    options: list[dict[str, str]] = []
    raw_options = data.get("alternatives")
    for item in raw_options if isinstance(raw_options, list) else []:
        if isinstance(item, dict) and str(item.get("name") or "").strip():
            options.append(
                {
                    "name": " ".join(str(item["name"]).split()),
                    "reason": _clip(str(item.get("reason") or ""), 120),
                }
            )
    source = "mock" if result.provider == ai.MOCK else result.provider
    texts = Texts(name, handles, bio, tagline or fallback.tagline, source, options)
    return _drop_taken(texts, ctx)


def _drop_taken(texts: Texts, ctx: MarketContext | None) -> Texts:
    """Leave out ideas that copy an existing channel; keep at most 5, no duplicates."""
    taken = ctx.taken_names() if ctx else set()
    options: list[dict[str, str]] = []
    for opt in texts.options:
        key = norm_name(opt["name"])
        if key and key not in taken and all(norm_name(o["name"]) != key for o in options):
            options.append(opt)
    if norm_name(texts.display_name) in taken and options:
        texts.display_name = options.pop(0)["name"]  # never copy an existing channel
    own = norm_name(texts.display_name)
    texts.options = [o for o in options if norm_name(o["name"]) != own][:5]
    return texts


# --- handle availability (YouTube only, official API) -------------------------------------

YOUTUBE_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"


def check_handles(
    settings: Settings,
    platform: PlatformCode,
    handles: list[str],
    client: httpx.Client | None = None,
) -> dict[str, str]:
    """``{"handle": "free" | "taken" | "unknown"}``; only YouTube can be checked."""
    result = dict.fromkeys(handles, "unknown")
    key = settings.youtube_api_key.get_secret_value()
    if platform != PlatformCode.YOUTUBE or not key or settings.trend_sources_mode != "live":
        return result
    own = client is None
    http = client or httpx.Client(timeout=settings.http_timeout_s)
    try:
        for handle in handles:
            try:
                res = http.get(
                    YOUTUBE_CHANNELS_URL,
                    params={"part": "id", "forHandle": f"@{handle}", "key": key},
                )
                if res.status_code >= 400:
                    continue
                result[handle] = "taken" if res.json().get("items") else "free"
            except (httpx.HTTPError, ValueError):
                continue  # never log the URL: it contains the API key
    finally:
        if own:
            http.close()
    return result


# --- tasks -----------------------------------------------------------------------------


def _unique_handles(texts: Texts, platform: PlatformCode) -> list[str]:
    seen: list[str] = []
    for raw in texts.handles:
        h = normalize_handle(raw, platform)
        if h and h not in seen:
            seen.append(h)
    if not seen:
        seen.append(normalize_handle(texts.display_name, platform))
    return seen[:4]


def _look(task: ChannelSetupTask, project: ContentProject) -> str:
    """Seed of the pictures: the area's name, or the one a fresh AI run picked."""
    look = (task.research or {}).get("look")
    return str(look) if look else project.slug


ART_SYSTEM = (
    "You write short visual subjects for an image model. Answer with one English noun "
    "phrase of at most 12 words that shows the topic as concrete, iconic objects. No names, "
    "no brands, no text, no quotes."
)


def _art_subject(
    session: Session,
    settings: Settings,
    project: ContentProject,
    user_id: int | None,
    idea: str = "",
) -> str:
    """What the pictures show, in English, e.g. "Krasse Fakten" -> "glowing light bulb,
    question marks and a magnifying glass". Falls back to the area's own words."""
    subs = ", ".join(str(t) for t in (project.subtopics or [])[:3])
    fallback = idea.strip() or f"{project.name}{f' ({subs})' if subs else ''}"
    wish = (
        f"\nOperator's own idea (the motif must follow it): {idea.strip()}" if idea.strip() else ""
    )
    try:
        result = ai.generate(
            session,
            settings,
            ai.AIRequest(
                purpose="channel_art",
                tier="text",
                messages=[
                    ai.AIMessage(
                        "user",
                        f"Topic area: {project.name}\nSub-topics: {subs or '-'}\n"
                        f"Description: {project.description or '-'}{wish}\n"
                        "Visual subject for the channel's logo and banner:",
                    )
                ],
                system=ART_SYSTEM,
                max_tokens=80,
                mock=lambda _req: fallback,
                content_project_id=project.id,
                user_id=user_id,
            ),
        )
    except ai.AIError as exc:
        log.info("art subject from template (%s)", exc.code)
        return fallback
    text = " ".join(result.text.replace('"', " ").split())[:160]
    return text or fallback


def _stored_art(settings: Settings, uri: object) -> Image.Image | None:
    if not isinstance(uri, str) or not uri:
        return None
    try:
        return Image.open(storage.resolve(settings, uri)).convert("RGB")
    except (storage.StorageError, OSError):
        return None


def _paint_art(
    session: Session | None,
    settings: Settings,
    task: ChannelSetupTask,
    project: ContentProject,
    seed: str,
    research: dict[str, Any],
    user_id: int | None,
    idea: str = "",
) -> tuple[Image.Image, Image.Image | None]:
    """Artwork of the current look: reused while the look stays (e.g. after a new
    name), painted anew by the image AI for a new look. Raises ImageAIError."""
    want_banner = RULES[task.platform].banner
    art = research.get("art")
    if isinstance(art, dict) and art.get("look") == seed:
        avatar = _stored_art(settings, art.get("avatar"))
        banner = _stored_art(settings, art.get("banner"))
        if avatar is not None and (banner is not None or not want_banner):
            return avatar, banner
    if session is not None:
        subject = _art_subject(session, settings, project, user_id, idea)
    else:
        subject = idea.strip() or project.name
    look = image_ai.design(subject, seed, branding.palette(seed))
    avatar = image_ai.paint(settings, look.avatar_prompt())
    banner = image_ai.paint(settings, look.banner_prompt()) if want_banner else None
    research["art"] = {
        "look": seed,
        "subject": subject,
        "style": look.style,
        "avatar": branding.store_png(settings, branding.art_png(avatar), "channel-art"),
        "banner": (
            branding.store_png(settings, branding.art_png(banner), "channel-art")
            if banner is not None
            else None
        ),
    }
    return avatar, banner


def _images(
    settings: Settings,
    task: ChannelSetupTask,
    project: ContentProject,
    tagline: str,
    session: Session | None = None,
    user_id: int | None = None,
    idea: str = "",
    replace_uploads: bool = False,
) -> None:
    """New pictures; the operator's own uploads stay unless ``replace_uploads``."""
    uploaded = [] if replace_uploads else list((task.research or {}).get("uploaded", []))
    want = ["avatar", "banner"] if RULES[task.platform].banner else ["avatar"]
    if all(k in uploaded for k in want):
        return  # both pictures are the operator's own: nothing to draw
    keep = {"avatar": task.avatar_uri, "banner": task.banner_uri}
    _draw_images(settings, task, project, tagline, session, user_id, idea)
    for kind in uploaded:
        setattr(task, f"{kind}_uri", keep[kind])
    task.research = {**(task.research or {}), "uploaded": uploaded}


def _draw_images(
    settings: Settings,
    task: ChannelSetupTask,
    project: ContentProject,
    tagline: str,
    session: Session | None = None,
    user_id: int | None = None,
    idea: str = "",
) -> None:
    """Profile picture and banner of one look (same colours, same style).

    With the image AI set up, the model paints both and the name is set as sharp
    text on the banner; otherwise (or if the AI fails) they are drawn locally."""
    seed = _look(task, project)
    research = dict(task.research or {})
    research.pop("image_note", None)
    want_banner = RULES[task.platform].banner
    if image_ai.available(settings):
        try:
            avatar, banner = _paint_art(
                session, settings, task, project, seed, research, user_id, idea
            )
        except image_ai.ImageAIError as exc:
            log.info("channel pictures drawn locally: %s", exc)
            research["image_source"] = "local"
            research["image_note"] = f"{exc} Die Bilder sind deshalb einfach gezeichnet."
        else:
            task.avatar_uri = branding.store_png(settings, branding.avatar_from_art(avatar))
            task.banner_uri = (
                branding.store_png(
                    settings, branding.banner_from_art(banner, task.display_name, tagline)
                )
                if want_banner and banner is not None
                else None
            )
            research["image_source"] = "ai"
            task.research = research
            return
    else:
        research["image_source"] = "local"
    task.avatar_uri = branding.store_png(settings, branding.avatar_png(task.display_name, seed))
    if want_banner:
        task.banner_uri = branding.store_png(
            settings, branding.banner_png(task.display_name, tagline, seed)
        )
    else:
        task.banner_uri = None
    task.research = research


def _email(settings: Settings, task: ChannelSetupTask, project: ContentProject) -> None:
    if not RULES[task.platform].needs_email:
        task.email, task.email_status, task.email_error = None, MailAliasStatus.NOT_NEEDED, None
        return
    local = mail_alias.local_part(project.slug, task.language.value, task.platform.value)
    res = mail_alias.create(
        settings, local, f"{project.name} {task.platform.value} {task.language.value}"
    )
    task.email, task.email_status = res.address, res.status
    task.email_rule_id, task.email_error = res.rule_id, res.error


def prepare_one(
    session: Session,
    settings: Settings,
    project: ContentProject,
    platform: PlatformCode,
    language: Language,
    user_id: int | None = None,
    channel_id: int | None = None,
    ctx: MarketContext | None = None,
) -> ChannelSetupTask:
    if ctx is None:
        ctx = market_context(session, settings, project, language)
    texts = write_texts(session, settings, project, platform, language, user_id, ctx)
    rules = RULES[platform]
    handles = _unique_handles(texts, platform)
    task = ChannelSetupTask(
        content_project_id=project.id,
        platform=platform,
        language=language,
        status=ChannelSetupStatus.OPEN,
        display_name=_clip(texts.display_name, rules.name_max),
        handle=handles[0],
        alt_handles=handles[1:],
        handle_check=check_handles(settings, platform, handles),
        bio=_clip(texts.bio, rules.bio_max),
        text_source=texts.source,
        name_options=[
            {"name": _clip(o["name"], rules.name_max), "reason": o["reason"]} for o in texts.options
        ],
        research={**ctx.to_json(), "tagline": texts.tagline},
        # set for an existing, not connected channel (e.g. a seed placeholder): finishing
        # the task turns that channel into the real one instead of adding a second one
        channel_id=channel_id,
    )
    # a free alternative goes first if the favourite is taken
    free = [h for h in handles if task.handle_check.get(h) == "free"]
    if task.handle_check.get(task.handle) == "taken" and free:
        task.handle = free[0]
        task.alt_handles = [h for h in handles if h != free[0]]
    _images(settings, task, project, texts.tagline, session, user_id)
    _email(settings, task, project)
    session.add(task)
    session.flush()
    audit.record(
        session,
        "channel_setup.prepare",
        user_id=user_id,
        agent=None if user_id else "channel_assistant",
        entity_type="channel_setup_tasks",
        entity_id=task.id,
        after={"project": project.name, "platform": platform.value, "language": language.value},
    )
    return task


def market_context(
    session: Session, settings: Settings, project: ContentProject, language: Language
) -> MarketContext:
    """Topic words, competitors and existing YouTube channels for the names."""
    return name_research.collect(session, settings, project, language, redis=get_redis())


def prepare(
    session: Session,
    settings: Settings,
    project: ContentProject,
    *,
    platforms: list[PlatformCode] | None = None,
    languages: list[Language] | None = None,
    user_id: int | None = None,
) -> list[ChannelSetupTask]:
    """Prepare a task for every missing channel of ``project`` (idempotent)."""
    if project.status == ContentProjectStatus.ARCHIVED:
        raise SetupError("Der Themenbereich ist archiviert.")
    project_id = project.id
    created: list[ChannelSetupTask] = []
    contexts: dict[Language, MarketContext] = {}  # one market search per language
    for slot in coverage(session, project).missing:
        if platforms and slot.platform not in platforms:
            continue
        if languages and slot.language not in languages:
            continue
        project = session.get(ContentProject, project_id) or project
        if slot.language not in contexts:
            contexts[slot.language] = market_context(session, settings, project, slot.language)
        created.append(
            prepare_one(
                session,
                settings,
                project,
                slot.platform,
                slot.language,
                user_id,
                # a placeholder becomes the real channel when the task is finished
                channel_id=slot.channel_id if slot.state == "placeholder" else None,
                ctx=contexts[slot.language],
            )
        )
    session.commit()
    return created


def prepare_for_channel(
    session: Session, settings: Settings, channel: Channel, user_id: int | None = None
) -> ChannelSetupTask:
    """Prepare name, bio and pictures for an existing channel that is not connected yet.

    Used for placeholders (e.g. the seed channels "YouTube Shorts DE"): the operator
    creates the real account with these values, and :func:`complete` updates the
    placeholder instead of adding a new channel."""
    if channel.auth_status in _CONNECTED:
        raise SetupError("Der Kanal ist schon verbunden.")
    if channel.content_project_id is None:
        raise SetupError("Der Kanal gehört zu keinem Themenbereich.")
    project = session.get(ContentProject, channel.content_project_id)
    if project is None or project.status == ContentProjectStatus.ARCHIVED:
        raise SetupError("Der Themenbereich ist archiviert.")
    plat = session.get(Platform, channel.platform_id)
    if plat is None or plat.code not in TARGET_PLATFORMS:
        raise SetupError("Für diese Plattform gibt es keinen Kanal-Assistenten.")
    task = session.scalar(
        select(ChannelSetupTask).where(
            ChannelSetupTask.content_project_id == project.id,
            ChannelSetupTask.platform == plat.code,
            ChannelSetupTask.language == channel.language,
            ChannelSetupTask.status == ChannelSetupStatus.OPEN,
        )
    )
    if task is not None:
        return task  # idempotent: one open task per slot
    channel_id = channel.id
    task = prepare_one(
        session, settings, project, plat.code, channel.language, user_id, channel_id=channel_id
    )
    session.commit()
    return task


#: what a single AI button renews: everything, or one field / both pictures together
PARTS = ("all", "name", "handle", "bio", "images")


def _tagline(task: ChannelSetupTask, project: ContentProject) -> str:
    """The banner's second line: the one the AI wrote last, else the template's."""
    stored = (task.research or {}).get("tagline")
    if stored:
        return str(stored)
    return template_texts(project, task.platform, task.language).tagline


def _next_after(
    current: str, candidates: list[str], key: Callable[[str], str] | None = None
) -> str | None:
    """The candidate after ``current`` in the list (wrapping), never ``current`` itself.

    Each click on an AI button moves one step further, so repeated clicks show
    different proposals even when the AI (or the template) answers the same."""

    def k(v: str) -> str:
        return key(v) if key else v

    seen: list[str] = []
    for c in candidates:
        if c and k(c) not in [k(x) for x in seen]:
            seen.append(c)
    keys = [k(c) for c in seen]
    if not seen:
        return None
    if k(current) not in keys:
        return seen[0]
    if len(seen) == 1:
        return None
    return seen[(keys.index(k(current)) + 1) % len(seen)]


def _bio_variants(project: ContentProject, language: Language) -> list[str]:
    """Hand-written bio patterns as a fallback when the AI repeats itself or is off."""
    topic = project.name.strip()
    subs = [str(t).strip() for t in project.subtopics or [] if str(t).strip()]
    words = ", ".join(subs[:3]) if subs else topic
    if language == Language.DE:
        return [
            f"{words}: kurz, verblüffend und ehrlich. Jeden Tag neue Shorts.",
            f"Hier lernst du in unter einer Minute etwas Neues über {topic}. Jeden Tag ein Short.",
            f"{topic} ohne Umwege: {words}. Folge für deinen täglichen Aha-Moment.",
            f"Kurze Videos über {words}. Geprüft, verständlich und nie langweilig.",
        ]
    return [
        f"{words}: short, surprising and honest. New shorts every day.",
        f"Learn something new about {topic} in under a minute. A new short every day.",
        f"{topic} without the fluff: {words}. Follow for your daily aha moment.",
        f"Short videos about {words}. Checked, clear and never boring.",
    ]


def _handles_for_name(name: str, platform: PlatformCode, language: Language) -> list[str]:
    """User names that match the channel name, e.g. "Krasse Fakten" -> "krassefakten"."""
    base = normalize_handle(name, platform)
    if not base:
        return []
    suffix = ["kompakt", "kurz", "_de"] if language == Language.DE else ["daily", "shorts", "_en"]
    out = [base] + [normalize_handle(f"{base}{s}", platform) for s in suffix]
    return [h for h in out if h]


def research_again(
    session: Session,
    settings: Settings,
    task: ChannelSetupTask,
    user_id: int | None = None,
    part: str = "all",
    idea: str = "",
) -> ChannelSetupTask:
    """AI buttons of the channel assistant: renew one field, both pictures, or everything.

    * ``name``: fresh market data and a new name; the pictures keep their colours
      but show the new name.
    * ``handle``: new user names that match the current name.
    * ``bio``: a new bio.
    * ``images``: a new colour pair and pattern for profile picture and banner
      together, so both still match each other.
    * ``all``: everything at once (name, user names, bio and pictures).

    Every click gives another proposal. The e-mail address always stays."""
    if part not in PARTS:
        raise SetupError("Unbekanntes Feld.")
    if task.status != ChannelSetupStatus.OPEN:
        raise SetupError("Die Aufgabe ist schon abgeschlossen.")
    project = task.content_project
    rules = RULES[task.platform]

    if part == "images":
        research = dict(task.research or {})
        research["look"] = f"{project.slug}-{secrets.token_hex(3)}"
        task.research = research
        _images(
            settings,
            task,
            project,
            _tagline(task, project),
            session,
            user_id,
            idea,
            replace_uploads=True,
        )
        _record_research(session, task, user_id, part, live=bool(research.get("live")))
        session.commit()
        return task

    ctx = market_context(session, settings, project, task.language)
    note = {
        "all": "",
        "name": f'The operator wants a different display_name than "{task.display_name}".',
        "handle": (
            f'Keep the channel name "{task.display_name}". The handles must match this name '
            f'and differ from "{task.handle}".'
        ),
        "bio": (
            f'Keep the channel name "{task.display_name}". Write a different bio than: "{task.bio}"'
        ),
    }[part]
    idea = " ".join(idea.split())[:300]
    if idea:
        note = (
            f"{note}\nThe operator's own idea, build on it and make it shine (keep its "
            f"intent, improve the wording): {idea}"
        ).strip()
    texts = write_texts(
        session, settings, project, task.platform, task.language, user_id, ctx, note
    )
    research = {**(task.research or {}), **ctx.to_json(), "tagline": texts.tagline}

    if part in ("all", "name"):
        previous = norm_name(task.display_name)
        if norm_name(texts.display_name) == previous:
            fresh = [o for o in texts.options if norm_name(o["name"]) != previous]
            if fresh:
                old = {"name": texts.display_name, "reason": "bisheriger Vorschlag"}
                texts.display_name = fresh[0]["name"]
                texts.options = [*fresh[1:], old]
        task.display_name = _clip(texts.display_name, rules.name_max)
        task.name_options = [
            {"name": _clip(o["name"], rules.name_max), "reason": o["reason"]} for o in texts.options
        ]

    if part in ("all", "handle"):
        if part == "all":
            handles = _unique_handles(texts, task.platform)
        else:
            # only user names that fit the current name: the AI's ideas that contain
            # it, plus simple variants of the name itself
            own = _handles_for_name(task.display_name, task.platform, task.language)
            ai_handles = _unique_handles(texts, task.platform)
            key = own[0].replace(".", "").replace("_", "") if own else ""
            fitting = [h for h in ai_handles if key and key in h.replace(".", "").replace("_", "")]
            pool = [*fitting, *own] or ai_handles
            pick = _next_after(task.handle, pool) or task.handle
            rest = [h for h in dict.fromkeys(pool) if h != pick]
            handles = [pick, *rest][:4]
        task.handle, task.alt_handles = handles[0], handles[1:]
        task.handle_check = check_handles(settings, task.platform, handles)
        free = [h for h in handles if task.handle_check.get(h) == "free"]
        if task.handle_check.get(task.handle) == "taken" and free:
            task.handle = free[0]
            task.alt_handles = [h for h in handles if h != free[0]]

    if part in ("all", "bio"):
        bio = _clip(texts.bio, rules.bio_max)
        if part == "bio":
            pool = [bio, *(_clip(b, rules.bio_max) for b in _bio_variants(project, task.language))]
            bio = _next_after(task.bio, pool, key=lambda b: " ".join(b.split()).casefold()) or bio
        task.bio = bio

    task.text_source = texts.source
    if part == "all":
        research["look"] = f"{project.slug}-{secrets.token_hex(3)}"
    task.research = research
    if part in ("all", "name"):
        # "all" gets a new look; a new name keeps the colours and only changes the lettering
        _images(
            settings,
            task,
            project,
            texts.tagline,
            session,
            user_id,
            replace_uploads=part == "all",
        )
    _record_research(session, task, user_id, part, live=ctx.live)
    session.commit()
    return task


def _record_research(
    session: Session, task: ChannelSetupTask, user_id: int | None, part: str, live: bool
) -> None:
    audit.record(
        session,
        "channel_setup.research",
        user_id=user_id,
        agent=None if user_id else "channel_assistant",
        entity_type="channel_setup_tasks",
        entity_id=task.id,
        after={"part": part, "display_name": task.display_name, "live": live},
    )


#: Accepted uploads (checked by content, not by name) and the largest file.
UPLOAD_FORMATS = {"PNG", "JPEG", "WEBP"}
UPLOAD_MAX_BYTES = 15 * 1024 * 1024
#: Smaller pictures are accepted but get a hint (platform minimums / sharpness).
UPLOAD_MIN = {"avatar": (400, 400), "banner": (2048, 1152)}


def upload_image(
    session: Session,
    settings: Settings,
    task: ChannelSetupTask,
    kind: str,
    data: bytes,
    user_id: int | None = None,
) -> str | None:
    """The operator's own profile picture or banner from the PC.

    The picture is cut to the platform size (800 x 800, banner 2560 x 1440, centred)
    and replaces the AI version; later renames and connecting the channel use it
    as it is. Returns a hint if the picture is smaller than recommended."""
    if task.status != ChannelSetupStatus.OPEN:
        raise SetupError("Die Aufgabe ist schon abgeschlossen.")
    if kind not in ("avatar", "banner"):
        raise SetupError("Unbekannte Bildart.")
    if kind == "banner" and not RULES[task.platform].banner:
        raise SetupError(f"{RULES[task.platform].label} hat kein Banner.")
    if not data:
        raise SetupError("Die Datei ist leer.")
    if len(data) > UPLOAD_MAX_BYTES:
        raise SetupError("Das Bild ist größer als 15 MB.")
    try:
        img = Image.open(io.BytesIO(data))
        fmt = img.format
        img.load()
    except (OSError, Image.DecompressionBombError) as exc:
        raise SetupError("Die Datei ist kein lesbares Bild (PNG, JPG oder WebP).") from exc
    if fmt not in UPLOAD_FORMATS:
        raise SetupError("Bitte ein PNG-, JPG- oder WebP-Bild hochladen.")
    min_w, min_h = UPLOAD_MIN[kind]
    hint = None
    if img.width < min_w or img.height < min_h:
        hint = (
            f"Dein Bild hat {img.width} × {img.height} Pixel, empfohlen sind mindestens "
            f"{min_w} × {min_h}. Es kann unscharf wirken."
        )
    if kind == "avatar":
        png = branding.avatar_from_art(img)
    else:
        png = branding.png_cover(img, branding.BANNER_SIZE)
    uri = branding.store_png(settings, png)
    setattr(task, f"{kind}_uri", uri)
    research = dict(task.research or {})
    research["uploaded"] = sorted({*research.get("uploaded", []), kind})
    task.research = research
    audit.record(
        session,
        "channel_setup.upload_image",
        user_id=user_id,
        entity_type="channel_setup_tasks",
        entity_id=task.id,
        after={"kind": kind, "size": [img.width, img.height]},
    )
    session.commit()
    return hint


def update(
    session: Session,
    settings: Settings,
    task: ChannelSetupTask,
    *,
    display_name: str | None = None,
    handle: str | None = None,
    bio: str | None = None,
) -> ChannelSetupTask:
    """Operator edits; a new name redraws the pictures, a new handle is normalised."""
    if task.status != ChannelSetupStatus.OPEN:
        raise SetupError("Die Aufgabe ist schon abgeschlossen.")
    rules = RULES[task.platform]
    if display_name is not None:
        name = _clip(display_name, rules.name_max)
        if not name:
            raise SetupError("Der Name darf nicht leer sein.")
        if name != task.display_name:
            task.display_name = name
            project = task.content_project
            _images(settings, task, project, _tagline(task, project), session)
    if handle is not None:
        new = normalize_handle(handle, task.platform)
        if new != task.handle:
            alts = [h for h in [task.handle, *task.alt_handles] if h != new]
            task.handle, task.alt_handles = new, alts[:4]
            check = check_handles(settings, task.platform, [new])
            task.handle_check = {**task.handle_check, **check}
    if bio is not None:
        text = _clip(bio, rules.bio_max)
        if not text:
            raise SetupError("Die Bio darf nicht leer sein.")
        task.bio = text
    session.commit()
    return task


def retry_email(session: Session, settings: Settings, task: ChannelSetupTask) -> ChannelSetupTask:
    if task.status != ChannelSetupStatus.OPEN:
        raise SetupError("Die Aufgabe ist schon abgeschlossen.")
    if task.email_status == MailAliasStatus.CREATED:
        return task
    _email(settings, task, task.content_project)
    session.commit()
    return task


def send_test_mail(session: Session, settings: Settings, task: ChannelSetupTask) -> OutgoingMail:
    """Send a short mail to the task's forwarding address over the engine's own SMTP.

    If it arrives in the operator's inbox, the whole chain (MX records, routing
    rule, verified destination) works and the address is safe to use for the
    account. Nothing is published; the mail only goes to the operator's domain."""
    if task.status != ChannelSetupStatus.OPEN:
        raise SetupError("Die Aufgabe ist schon abgeschlossen.")
    if not task.email:
        raise SetupError("Für diesen Kanal gibt es keine eigene E-Mail-Adresse.")
    if task.email_status != MailAliasStatus.CREATED:
        raise SetupError(
            "Die Weiterleitung ist noch nicht bei Cloudflare angelegt. Erst anlegen, dann testen."
        )
    mail = mailer.send(
        session,
        settings,
        task.email,
        f"Kanalfabrik Testmail für {task.display_name}",
        "Diese Mail prüft die Weiterleitung für das neue Konto.\n\n"
        f"Adresse: {task.email}\nPlattform: {task.platform.value}, Sprache: "
        f"{task.language.value}\n\nWenn du sie in deinem Postfach siehst, funktioniert die "
        "Adresse und du kannst das Konto damit anlegen.",
        kind="alias_test",
    )
    session.commit()
    return mail


def complete(
    session: Session, task: ChannelSetupTask, user_id: int, *, handle: str | None = None
) -> Channel:
    """The operator created the account: add the channel to the engine (paused, not connected).

    Like any new channel it cannot publish before it is connected and its safety
    bounds are set (``max_posts_per_day = 0``)."""
    if task.status != ChannelSetupStatus.OPEN:
        raise SetupError("Die Aufgabe ist schon abgeschlossen.")
    if handle:
        task.handle = normalize_handle(handle, task.platform)
    plat = session.scalar(select(Platform).where(Platform.code == task.platform))
    if plat is None:
        raise SetupError("Plattform fehlt in der Datenbank.")
    placeholder = session.get(Channel, task.channel_id) if task.channel_id else None
    if placeholder is not None and placeholder.auth_status in _CONNECTED:
        placeholder = None  # connected meanwhile: never rename a live channel
    name = task.display_name
    same_name = select(Channel.id).where(
        Channel.platform_id == plat.id, Channel.language == task.language, Channel.name == name
    )
    if placeholder is not None:
        same_name = same_name.where(Channel.id != placeholder.id)
    if session.scalar(same_name) is not None:
        name = _clip(f"{task.display_name} (@{task.handle})", 120)
    if placeholder is not None:
        # the placeholder becomes the real channel; it stays paused until connected
        channel = placeholder
        channel.name = name
        channel.description = task.bio
        strategy = {k: v for k, v in (channel.strategy or {}).items() if k != "placeholder"}
        channel.strategy = {**strategy, "handle": task.handle, "setup_task_id": task.id}
    else:
        channel = Channel(
            platform_id=plat.id,
            content_project_id=task.content_project_id,
            language=task.language,
            name=name,
            description=task.bio,
            auth_status=ChannelAuthStatus.NOT_CONNECTED,
            is_paused=True,
            min_posts_per_day=0,
            max_posts_per_day=0,
            strategy={"handle": task.handle, "setup_task_id": task.id},
        )
        session.add(channel)
    session.flush()
    task.status = ChannelSetupStatus.DONE
    task.channel_id = channel.id
    task.completed_at = datetime.now(UTC)
    audit.record(
        session,
        "channel_setup.complete",
        user_id=user_id,
        entity_type="channel_setup_tasks",
        entity_id=task.id,
        after={"channel_id": channel.id, "handle": task.handle},
    )
    session.commit()
    return channel


def dismiss(
    session: Session, settings: Settings, task: ChannelSetupTask, user_id: int
) -> ChannelSetupTask:
    if task.status != ChannelSetupStatus.OPEN:
        raise SetupError("Die Aufgabe ist schon abgeschlossen.")
    if task.email_status == MailAliasStatus.CREATED and task.email_rule_id:
        mail_alias.delete(settings, task.email_rule_id)
    task.status = ChannelSetupStatus.DISMISSED
    task.completed_at = datetime.now(UTC)
    audit.record(
        session,
        "channel_setup.dismiss",
        user_id=user_id,
        entity_type="channel_setup_tasks",
        entity_id=task.id,
    )
    session.commit()
    return task


def open_tasks(session: Session, project_id: int | None = None) -> list[ChannelSetupTask]:
    q = select(ChannelSetupTask).where(ChannelSetupTask.status == ChannelSetupStatus.OPEN)
    if project_id is not None:
        q = q.where(ChannelSetupTask.content_project_id == project_id)
    return list(session.scalars(q.order_by(ChannelSetupTask.id)))
