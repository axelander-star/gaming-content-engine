"""The Facebook Page behind an Instagram channel, as a channel of its own.

An Instagram professional account that is connected through the Meta login always
belongs to a Facebook Page (Instagram creates one when the account is set up).
The Page token the Instagram channel stores is the token of that Page, so the
engine can run the Page without a second login:

* :func:`link_from_instagram` creates (or updates) a Facebook channel in the same
  topic area and language, with the same Page token, safety bounds and pause
  state as the Instagram channel ("Facebook-Seite" in the dashboard).
* :func:`sync_profile` fills the Page from the channel assistant's values:
  short description (``about``), profile picture and cover photo.
* :func:`mirror` copies every Instagram video that is ready (or already out) to
  the Facebook channel; the Publishing Strategy Agent decides when it goes out,
  like for any other channel, and it is only published for real with
  ``PUBLISHING_MODE=live``.
* :func:`check` looks at the Page token and the profile; problems become
  notifications (bell, phone).

Agent 27 (``agents/facebook_page.py``) runs all of this regularly.

Official Graph API endpoints only (reference v26.0, checked 28.11.2026; see
docs/API_INTEGRATIONS.md):

* ``GET /me?fields=id,name`` with a Page token returns the Page.
* ``POST /{page-id}`` with ``about`` ("Description" in the Page info; MANAGE task,
  ``pages_manage_metadata``) and with ``cover=<photo id>`` (EDIT_PROFILE,
  ``business_management``).
* ``POST /{page-id}/photos`` with ``published=false`` and the file as multipart
  ``source`` returns the id of an unpublished photo (CREATE_CONTENT,
  ``pages_manage_posts``); nothing appears in the feed.
* ``POST /{page-id}/picture`` with ``photo=<photo id>`` sets the profile picture
  (MANAGE, ``pages_read_engagement``, ``pages_show_list``).

Creating a Page through the API is not possible (and not needed: Instagram made it).
"""

from __future__ import annotations

import io
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import crypto
from core.config import Settings
from core.enums import ChannelAuthStatus, NotificationLevel, PlatformCode, VideoStatus
from models.channel_setup import ChannelSetupTask
from models.channels import Channel, ChannelCredential, Platform
from models.production import Variant
from models.projects import ContentProject
from services import (
    audit,
    branding,
    campaigns,
    channel_setup,
    crosspost,
    meta,
    notify,
    platform,
    profile_sync,
    storage,
)
from services.platform import AuthExpiredError, PlatformError, TransientError

log = logging.getLogger("facebook_page")

ACTOR = "facebook_page"
#: Facebook shows at most about 100 characters of the Page description.
ABOUT_MAX = 100
#: Cover photo: 16:9 keeps the whole picture on phones; the desktop shows the middle.
COVER_SIZE = (1640, 924)
#: Instagram videos from these states are copied to Facebook.
MIRROR_STATUSES = (VideoStatus.READY_TO_PUBLISH, VideoStatus.SCHEDULED, VideoStatus.PUBLISHED)
LOOKBACK_DAYS = 7
#: A failed profile is tried again at most this often, once a day.
SYNC_ATTEMPTS = 5
SYNC_RETRY = timedelta(hours=24)
#: The Page token is checked every few hours, not on every run.
CHECK_EVERY = timedelta(hours=6)
NEEDED = {
    "pages_manage_posts": "Reels auf der Seite veröffentlichen",
    "pages_manage_metadata": "Beschreibung und Profilbild der Seite setzen",
    "business_management": "Titelbild der Seite setzen",
}


class PageError(Exception):
    """The Page could not be linked or written (German message for the dashboard)."""


# --- helpers ------------------------------------------------------------------------


def _cred(session: Session, channel: Channel) -> ChannelCredential | None:
    return session.scalar(
        select(ChannelCredential).where(ChannelCredential.channel_id == channel.id)
    )


def page_channel_of(session: Session, instagram: Channel) -> Channel | None:
    """The Facebook channel that mirrors ``instagram``, if there is one."""
    fb_id = (instagram.strategy or {}).get("facebook_page_channel_id")
    if isinstance(fb_id, int) and not isinstance(fb_id, bool):
        channel = session.get(Channel, fb_id)
        if channel is not None and channel.platform.code == PlatformCode.FACEBOOK:
            return channel
    return None


def source_of(session: Session, facebook: Channel) -> Channel | None:
    """The Instagram channel a Facebook channel mirrors, if it was made from one."""
    ig_id = (facebook.strategy or {}).get("mirror_of")
    if isinstance(ig_id, int) and not isinstance(ig_id, bool):
        channel = session.get(Channel, ig_id)
        if channel is not None and channel.platform.code == PlatformCode.INSTAGRAM:
            return channel
    return None


def _facebook_platform(session: Session) -> Platform:
    plat = session.scalar(select(Platform).where(Platform.code == PlatformCode.FACEBOOK))
    if plat is None:
        plat = Platform(code=PlatformCode.FACEBOOK, name="Facebook Reels")
        session.add(plat)
        session.flush()
    return plat


def _free_name(session: Session, plat: Platform, channel: Channel, wanted: str) -> str:
    """``wanted`` or, if another Facebook channel of the language has it, a variant."""
    base = " ".join(wanted.split())[:110] or "Facebook-Seite"
    for name in (base, f"{base} (Facebook)", *(f"{base} ({i})" for i in range(2, 20))):
        clash = session.scalar(
            select(Channel.id).where(
                Channel.platform_id == plat.id,
                Channel.language == channel.language,
                Channel.name == name,
            )
        )
        if clash is None:
            return name
    return f"{base} #{channel.id}"


def missing_permissions(scopes: list[Any]) -> list[str]:
    """What the Meta login did not grant, as plain German for the dashboard."""
    granted = {str(s) for s in scopes or []}
    return [label for perm, label in NEEDED.items() if perm not in granted]


# --- link ---------------------------------------------------------------------------


def link_from_instagram(
    session: Session, settings: Settings, instagram: Channel, user_id: int | None = None
) -> Channel:
    """Create or update the Facebook channel of a Meta-connected Instagram channel.

    The Page is looked up with the Instagram channel's Page token, so it is always
    exactly the Page the Instagram account belongs to. Raises :class:`PageError`
    (or a platform error) when that is not possible; nothing is changed then."""
    if instagram.platform.code != PlatformCode.INSTAGRAM:
        raise PageError("Nur ein Instagram-Kanal hat eine Facebook-Seite")
    ig_cred = _cred(session, instagram)
    if ig_cred is None or ig_cred.provider != meta.PROVIDER or not ig_cred.access_token_enc:
        raise PageError(
            "Instagram ist nicht über den Facebook-Login verbunden; die Seite kann die "
            "Engine nur so übernehmen"
        )
    token = meta.page_token(settings, ig_cred)
    page = meta._get("me", {"fields": "id,name", "access_token": token}, "Facebook-Seite")
    page_id, page_name = str(page.get("id") or ""), str(page.get("name") or "")
    if not page_id:
        raise PageError("Meta hat keine Facebook-Seite zu diesem Instagram-Konto geliefert")
    plat = _facebook_platform(session)
    channel = session.scalar(
        select(Channel).where(
            Channel.platform_id == plat.id, Channel.external_channel_id == page_id
        )
    ) or page_channel_of(session, instagram)
    if channel is None:
        # a Facebook channel the operator already made for this area and language
        spare = [
            c
            for c in session.scalars(
                select(Channel).where(
                    Channel.platform_id == plat.id,
                    Channel.content_project_id == instagram.content_project_id,
                    Channel.language == instagram.language,
                    Channel.auth_status == ChannelAuthStatus.NOT_CONNECTED,
                )
            )
            if source_of(session, c) is None
        ]
        channel = spare[0] if len(spare) == 1 else None
    if channel is not None and channel.content_project_id != instagram.content_project_id:
        raise PageError(
            f"Die Facebook-Seite „{page_name}“ gehört schon zu einem Kanal in einem anderen "
            "Themenbereich"
        )
    created = channel is None
    if channel is None:
        channel = Channel(
            platform_id=plat.id,
            content_project_id=instagram.content_project_id,
            language=instagram.language,
            name=_free_name(session, plat, instagram, page_name or instagram.name),
            auth_status=ChannelAuthStatus.NOT_CONNECTED,
            # the operator's choices for Instagram carry over (bounds, pause)
            is_paused=instagram.is_paused,
            min_posts_per_day=instagram.min_posts_per_day,
            max_posts_per_day=instagram.max_posts_per_day,
            min_interval_minutes=instagram.min_interval_minutes,
            description=instagram.description,
            audience_notes=instagram.audience_notes,
        )
        session.add(channel)
        session.flush()
    elif channel.max_posts_per_day == 0:
        # a channel nobody configured yet gets the Instagram channel's choices
        channel.is_paused = instagram.is_paused
        channel.min_posts_per_day = instagram.min_posts_per_day
        channel.max_posts_per_day = instagram.max_posts_per_day
        channel.min_interval_minutes = instagram.min_interval_minutes
    cred = _cred(session, channel) or ChannelCredential(
        channel_id=channel.id, provider=meta.PROVIDER
    )
    cred.provider = meta.PROVIDER
    cred.access_token_enc = crypto.encrypt(settings, token)
    cred.refresh_token_enc = None
    cred.expires_at = None
    cred.scopes = list(ig_cred.scopes or [])
    cred.external_account_id = page_id
    cred.external_account_name = page_name or page_id
    cred.connected_by_user_id = user_id or ig_cred.connected_by_user_id
    cred.last_refreshed_at = datetime.now(UTC)
    cred.last_error = None
    session.add(cred)
    before = channel.auth_status.value
    channel.external_channel_id = page_id
    channel.auth_status = (
        ChannelAuthStatus.AUTHORIZED
        if meta.PUBLISH_SCOPE[PlatformCode.FACEBOOK] in (cred.scopes or [])
        else ChannelAuthStatus.CONNECTED_RESTRICTED
    )
    channel.strategy = {
        **(channel.strategy or {}),
        "mirror_of": instagram.id,
        "auto_created": True,  # the engine runs this Page (made or taken over)
        "missing_permissions": missing_permissions(cred.scopes or []),
    }
    instagram.strategy = {**(instagram.strategy or {}), "facebook_page_channel_id": channel.id}
    audit.record(
        session,
        "channel.facebook_page_linked",
        user_id=user_id,
        entity_type="channels",
        entity_id=channel.id,
        before={"auth_status": before},
        after={
            "created": created,
            "instagram_channel_id": instagram.id,
            "page": page_name,
            "auth_status": channel.auth_status.value,
        },
    )
    session.flush()
    log.info(
        "facebook page linked",
        extra={"channel": channel.id, "instagram": instagram.id, "new_channel": created},
    )
    return channel


# --- profile ------------------------------------------------------------------------


@dataclass
class ProfileResult:
    ok: bool
    applied: list[str] = field(default_factory=list)
    manual: list[str] = field(default_factory=list)
    error: str | None = None
    at: str = ""
    attempts: int = 1

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def short_about(text: str, limit: int = ABOUT_MAX) -> str:
    """One line of at most ``limit`` characters, cut at a word."""
    line = " ".join(text.split())
    if len(line) <= limit:
        return line
    cut = line[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,.;:-–")
    return f"{cut}…"


def _setup_task(session: Session, facebook: Channel) -> ChannelSetupTask | None:
    source = source_of(session, facebook)
    for channel in (facebook, source):
        if channel is None:
            continue
        has_task = (channel.strategy or {}).get("setup_task_id") is not None or (
            session.scalar(
                select(ChannelSetupTask.id).where(ChannelSetupTask.channel_id == channel.id)
            )
            is not None
        )
        if has_task:
            return profile_sync.setup_task(session, channel)
    return None


def cover_png(session: Session, settings: Settings, task: ChannelSetupTask) -> bytes:
    """The cover photo: the area's banner (same look as YouTube) if there is one,
    else a banner in the colours of the Instagram profile, drawn locally."""
    banner_uri = task.banner_uri or session.scalar(
        select(ChannelSetupTask.banner_uri)
        .where(
            ChannelSetupTask.content_project_id == task.content_project_id,
            ChannelSetupTask.language == task.language,
            ChannelSetupTask.banner_uri.is_not(None),
        )
        .order_by(ChannelSetupTask.id.desc())
        .limit(1)
    )
    if banner_uri:
        try:
            with Image.open(io.BytesIO(storage.resolve(settings, banner_uri).read_bytes())) as img:
                return branding.png_cover(img.convert("RGB"), COVER_SIZE)
        except (storage.StorageError, OSError):
            log.info("banner not readable, drawing the cover", extra={"task": task.id})
    project = session.get(ContentProject, task.content_project_id)
    seed = str((task.research or {}).get("look") or (project.slug if project else task.handle))
    tagline = channel_setup.banner_tagline(task, project) if project is not None else ""
    drawn = branding.banner_png(task.display_name, tagline, seed)
    with Image.open(io.BytesIO(drawn)) as img:
        return branding.png_cover(img.convert("RGB"), COVER_SIZE)


def _upload_photo(token: str, page_id: str, png: bytes, name: str) -> str:
    """An unpublished Page photo (not shown in the feed); returns its id."""
    with platform.http_client(120) as client:
        try:
            res = client.post(
                f"{meta.GRAPH}/{page_id}/photos",
                params={"published": "false", "access_token": token},
                files={"source": (name, png, "image/png")},
            )
        except httpx.HTTPError as exc:
            raise TransientError("Foto-Upload: Meta nicht erreichbar") from exc
    data = meta._check(res, "Foto-Upload")
    photo_id = str(data.get("id") or "")
    if not photo_id:
        raise PlatformError("Foto-Upload ohne Foto-ID beantwortet")
    return photo_id


def _short(exc: Exception) -> str:
    return " ".join(str(exc).split())[:200]


def sync_profile(
    session: Session, settings: Settings, facebook: Channel, force: bool = False
) -> ProfileResult:
    """Write description, profile picture and cover photo to the Page.

    Each part is tried on its own, so a missing permission for one does not stop
    the others. Only Pages whose Instagram channel came from the channel assistant
    are written (an existing Page of the operator is never overwritten). Never
    raises: the outcome is stored in ``channel.strategy["profile_sync"]``."""
    now = datetime.now(UTC)
    previous = (facebook.strategy or {}).get("profile_sync") or {}
    attempts = 1 if force else int(previous.get("attempts") or 0) + 1
    result = ProfileResult(ok=False, at=now.isoformat(), attempts=attempts)
    try:
        _sync(session, settings, facebook, result)
    except (PageError, PlatformError) as exc:
        result.error = _short(exc)
    except storage.StorageError:
        result.error = "Bilddatei aus dem Kanal-Assistenten nicht gefunden"
    if result.applied and not result.manual:
        result.ok = True
        result.error = None
    elif result.applied and result.error is None:
        result.error = "Nicht alles übertragen: " + ", ".join(result.manual)
    facebook.strategy = {**(facebook.strategy or {}), "profile_sync": result.as_dict()}
    session.flush()
    log.info(
        "facebook profile sync",
        extra={"channel": facebook.id, "ok": result.ok, "applied": result.applied},
    )
    return result


def _sync(session: Session, settings: Settings, facebook: Channel, result: ProfileResult) -> None:
    if facebook.platform.code != PlatformCode.FACEBOOK:
        raise PageError("Kein Facebook-Kanal")
    cred = _cred(session, facebook)
    if (
        cred is None
        or facebook.auth_status not in (
            ChannelAuthStatus.AUTHORIZED, ChannelAuthStatus.CONNECTED_RESTRICTED
        )
        or not facebook.external_channel_id
    ):  # fmt: skip
        raise PageError("Facebook-Seite ist nicht verbunden")
    task = _setup_task(session, facebook)
    if task is None:
        raise PageError(
            "Der Kanal stammt nicht aus dem Kanal-Assistenten; das Profil der Seite bleibt "
            "unverändert"
        )
    token = meta.page_token(settings, cred)
    page_id = facebook.external_channel_id
    about = short_about(task.bio or facebook.description or "")
    if about:
        try:
            meta._post(page_id, {"about": about, "access_token": token}, "Beschreibung")
            result.applied.append("Beschreibung")
        except AuthExpiredError:
            raise
        except PlatformError as exc:
            result.manual.append("Beschreibung")
            result.error = f"Beschreibung: {_short(exc)}"
    if task.avatar_uri:
        try:
            png = storage.resolve(settings, task.avatar_uri).read_bytes()
            photo = _upload_photo(token, page_id, png, "profile.png")
            meta._post(f"{page_id}/picture", {"photo": photo, "access_token": token}, "Profilbild")
            result.applied.append("Profilbild")
        except AuthExpiredError:
            raise
        except (PlatformError, storage.StorageError) as exc:
            result.manual.append("Profilbild")
            result.error = result.error or f"Profilbild: {_short(exc)}"
    try:
        photo = _upload_photo(token, page_id, cover_png(session, settings, task), "cover.png")
        meta._post(page_id, {"cover": photo, "access_token": token}, "Titelbild")
        result.applied.append("Titelbild")
    except AuthExpiredError:
        raise
    except PlatformError as exc:
        result.manual.append("Titelbild")
        result.error = result.error or f"Titelbild: {_short(exc)}"
    if not result.applied and not result.manual:
        raise PageError("Im Kanal-Assistenten ist noch nichts vorbereitet")


def sync_due(facebook: Channel, now: datetime) -> bool:
    """Whether the agent should (re)try the profile now."""
    if not (facebook.strategy or {}).get("auto_created"):
        return False
    previous = (facebook.strategy or {}).get("profile_sync")
    if not previous:
        return True
    if previous.get("ok") or int(previous.get("attempts") or 0) >= SYNC_ATTEMPTS:
        return False
    try:
        at = datetime.fromisoformat(str(previous.get("at")))
    except ValueError:
        return True
    return now - at >= SYNC_RETRY


# --- mirror -------------------------------------------------------------------------


def _already_there(session: Session, variant: Variant, facebook: Channel) -> bool:
    query = select(Variant.id).where(Variant.channel_id == facebook.id)
    if variant.clip_id is not None:
        query = query.where(
            Variant.clip_id == variant.clip_id, Variant.variant_label == variant.variant_label
        )
    elif variant.library_item_id is not None:
        query = query.where(Variant.library_item_id == variant.library_item_id)
    else:
        return True
    return session.scalar(query.limit(1)) is not None


def mirror(
    session: Session, settings: Settings, now: datetime | None = None, limit: int = 200
) -> dict[str, Any]:
    """Copy fresh Instagram videos to the Facebook channel of the same account."""
    now = now or datetime.now(UTC)
    made: list[dict[str, int]] = []
    skipped: list[dict[str, Any]] = []
    pairs = []
    for fb in session.scalars(
        select(Channel)
        .join(Platform, Channel.platform_id == Platform.id)
        .where(Platform.code == PlatformCode.FACEBOOK)
        .order_by(Channel.id)
    ):
        source = source_of(session, fb)
        if source is not None and not fb.is_paused and (fb.strategy or {}).get("mirror", True):
            pairs.append((source, fb))
    for instagram, fb in pairs:
        rows = session.scalars(
            select(Variant)
            .where(
                Variant.channel_id == instagram.id,
                Variant.status.in_(MIRROR_STATUSES),
                Variant.updated_at >= now - timedelta(days=LOOKBACK_DAYS),
            )
            .order_by(Variant.id)
            .limit(limit)
        ).all()
        for variant in rows:
            if _already_there(session, variant, fb):
                continue
            # campaign briefs name their channels themselves
            if campaigns.for_variant(session, variant) is not None:
                continue
            result = crosspost.copy_to(session, variant, fb)
            if isinstance(result, str):
                skipped.append({"variant_id": variant.id, "channel_id": fb.id, "reason": result})
                continue
            result.concept = {**(result.concept or {}), "facebook_mirror_of": variant.id}
            made.append({"variant_id": variant.id, "copy_id": result.id, "channel_id": fb.id})
    session.flush()
    return {"pages": len(pairs), "copies": made, "skipped": skipped}


# --- watch --------------------------------------------------------------------------


def _warn(session: Session, key: str, title: str, body: str, level: NotificationLevel) -> bool:
    now = datetime.now(UTC)
    if notify.recently(session, key, 24, now):
        return False
    notify.add(
        session, title, body, level=level, kind="channel", link="/einstellungen", dedup_key=key
    )
    return True


def check(session: Session, settings: Settings, facebook: Channel, now: datetime) -> list[str]:
    """Look at the Page token and the profile; returns the problems found."""
    problems: list[str] = []
    strategy = dict(facebook.strategy or {})
    last = strategy.get("checked_at")
    due = True
    if isinstance(last, str):
        try:
            due = now - datetime.fromisoformat(last) >= CHECK_EVERY
        except ValueError:
            due = True
    cred = _cred(session, facebook)
    if due and cred is not None and cred.access_token_enc and facebook.auth_status in (
        ChannelAuthStatus.AUTHORIZED, ChannelAuthStatus.CONNECTED_RESTRICTED
    ):  # fmt: skip
        try:
            meta._get(
                "me", {"fields": "id", "access_token": meta.page_token(settings, cred)}, "Prüfung"
            )
        except AuthExpiredError as exc:
            facebook.auth_status = ChannelAuthStatus.EXPIRED  # the watchdog warns from here
            cred.last_error = _short(exc)
            problems.append("Verbindung abgelaufen")
        except TransientError:
            pass  # try again next time
        except PlatformError as exc:
            cred.last_error = _short(exc)
            problems.append(f"Seite nicht erreichbar: {_short(exc)}")
        strategy["checked_at"] = now.isoformat()
    missing = missing_permissions(cred.scopes if cred else [])
    strategy["missing_permissions"] = missing
    facebook.strategy = strategy
    if missing and facebook.auth_status != ChannelAuthStatus.EXPIRED:
        problems.append("Es fehlen Rechte: " + ", ".join(missing))
        _warn(
            session,
            f"fb_permissions:{facebook.id}",
            f"{facebook.name}: Facebook-Seite braucht mehr Rechte",
            "Für " + ", ".join(missing) + " fehlen Häkchen in der Meta-Login-Konfiguration. "
            "Anleitung: Fragezeichen oben auf der Seite Einstellungen. Danach Instagram einmal "
            "neu verbinden.",
            NotificationLevel.WARNING,
        )
    sync = strategy.get("profile_sync") or {}
    if sync and not sync.get("ok") and int(sync.get("attempts") or 0) >= SYNC_ATTEMPTS:
        problems.append(f"Profil nicht übertragen: {sync.get('error')}")
        _warn(
            session,
            f"fb_profile:{facebook.id}",
            f"{facebook.name}: Profil der Facebook-Seite nicht vollständig",
            f"{sync.get('error') or 'Unbekannter Fehler'}. Im Studio unter Einstellungen → "
            "Kanäle „Erneut übertragen“ wählen.",
            NotificationLevel.INFO,
        )
    session.flush()
    return problems


@dataclass
class RunResult:
    linked: list[int] = field(default_factory=list)
    synced: list[int] = field(default_factory=list)
    copies: int = 0
    problems: dict[int, list[str]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def run(session: Session, settings: Settings, now: datetime | None = None) -> RunResult:
    """One round of the Facebook Page agent: link, fill, mirror, watch."""
    now = now or datetime.now(UTC)
    out = RunResult()
    instagram_channels = session.scalars(
        select(Channel)
        .join(Platform, Channel.platform_id == Platform.id)
        .where(
            Platform.code == PlatformCode.INSTAGRAM,
            Channel.auth_status.in_(
                (ChannelAuthStatus.AUTHORIZED, ChannelAuthStatus.CONNECTED_RESTRICTED)
            ),
        )
        .order_by(Channel.id)
    ).all()
    for ig in instagram_channels:
        cred = _cred(session, ig)
        if cred is None or cred.provider != meta.PROVIDER:
            continue  # Instagram Login (without a Page): nothing to take over
        fb = page_channel_of(session, ig)
        fb_cred = _cred(session, fb) if fb is not None else None
        if (
            fb is None
            or fb_cred is None
            or fb_cred.access_token_enc is None
            or fb.auth_status == ChannelAuthStatus.EXPIRED
            # Instagram was connected again (new token or new permissions)
            or (
                cred.last_refreshed_at is not None
                and (
                    fb_cred.last_refreshed_at is None
                    or cred.last_refreshed_at > fb_cred.last_refreshed_at
                )
            )
        ):
            try:
                fb = link_from_instagram(session, settings, ig)
                out.linked.append(fb.id)
            except (PageError, PlatformError) as exc:
                out.problems.setdefault(ig.id, []).append(_short(exc))
                continue
    for fb in session.scalars(
        select(Channel)
        .join(Platform, Channel.platform_id == Platform.id)
        .where(Platform.code == PlatformCode.FACEBOOK)
        .order_by(Channel.id)
    ).all():
        if source_of(session, fb) is None:
            continue
        if fb.auth_status != ChannelAuthStatus.EXPIRED and sync_due(fb, now):
            sync_profile(session, settings, fb)
            out.synced.append(fb.id)
        problems = check(session, settings, fb, now)
        if problems:
            out.problems.setdefault(fb.id, []).extend(problems)
    out.copies = len(mirror(session, settings, now)["copies"])
    session.flush()
    return out
