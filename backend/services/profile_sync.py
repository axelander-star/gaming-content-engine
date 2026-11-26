"""Fill a freshly connected channel's profile from the channel assistant.

The channel assistant prepares name, description, profile picture and banner.
After the operator connects a YouTube channel, the engine writes what the
official YouTube Data API allows (checked against the reference, 26.11.2026):

* ``channels.update`` (part ``brandingSettings``, 50 quota units): description
  (max. 1,000 characters) and keywords (max. 500 characters in total). The call
  replaces every writable field of the part, so the current settings are read
  first (``channels.list``, 1 unit) and sent back with only our fields changed;
  the title is never changed (YouTube refuses that).
* ``channelBanners.insert`` (50 units): the banner (16:9, at least 2048 x 1152,
  max. 6 MB; ours is 2560 x 1440 PNG), then its URL goes into
  ``brandingSettings.image.bannerExternalUrl`` of the same ``channels.update``.

There is no API for the profile picture or the channel links, on YouTube as on
TikTok and Instagram: the dashboard offers those for download and copying.

The result is kept in ``channel.strategy["profile_sync"]`` so the dashboard can
show what was written and offer "try again". Nothing here publishes a video.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import ChannelAuthStatus, PlatformCode
from models.channel_setup import ChannelSetupTask
from models.channels import Channel, ChannelCredential
from models.projects import ContentProject
from services import platform, quota, storage, youtube
from services.sources.base import QuotaExceededError

log = logging.getLogger("profile_sync")

DESCRIPTION_MAX = 1000
KEYWORDS_MAX = 500
BANNER_MAX_BYTES = 6 * 1024 * 1024
#: channels.list (1) + channelBanners.insert (50) + channels.update (50)
UNITS = 101
BANNER_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/channelBanners/insert"


class ProfileSyncError(Exception):
    """The profile could not be written (German message for the dashboard)."""


@dataclass
class SyncResult:
    ok: bool
    applied: list[str] = field(default_factory=list)
    manual: list[str] = field(default_factory=list)
    error: str | None = None
    at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _task(session: Session, channel: Channel) -> ChannelSetupTask | None:
    task_id = (channel.strategy or {}).get("setup_task_id")
    if isinstance(task_id, int):
        task = session.get(ChannelSetupTask, task_id)
        if task is not None:
            return task
    return session.scalar(
        select(ChannelSetupTask)
        .where(ChannelSetupTask.channel_id == channel.id)
        .order_by(ChannelSetupTask.id.desc())
        .limit(1)
    )


def keywords(channel: Channel, project: ContentProject | None) -> str:
    """Space separated, multi-word terms quoted, at most 500 characters."""
    words: list[str] = []
    if project is not None:
        words.append(project.name)
        words += [str(s) for s in project.subtopics or []]
    handle = (channel.strategy or {}).get("handle")
    if isinstance(handle, str) and handle:
        words.append(handle.lstrip("@"))
    out: list[str] = []
    seen: set[str] = set()
    total = 0
    for raw in words:
        term = " ".join(raw.replace('"', "").split())
        if not term or term.lower() in seen:
            continue
        token = f'"{term}"' if " " in term else term
        if total + len(token) + (1 if out else 0) > KEYWORDS_MAX:
            break
        out.append(token)
        seen.add(term.lower())
        total += len(token) + (1 if len(out) > 1 else 0)
    return " ".join(out)


def _check(res: httpx.Response, where: str) -> dict[str, Any]:
    if res.status_code in (401,):
        raise ProfileSyncError("YouTube-Anmeldung abgelaufen, bitte Kanal neu verbinden")
    if res.status_code == 403:
        raise ProfileSyncError(
            f"YouTube hat {where} abgelehnt (fehlende Berechtigung oder Kontingent)"
        )
    if res.status_code >= 400:
        raise ProfileSyncError(f"YouTube {where} fehlgeschlagen ({res.status_code})")
    try:
        data = res.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def sync_youtube(
    session: Session,
    settings: Settings,
    redis: Redis,
    channel: Channel,
    client: httpx.Client | None = None,
) -> SyncResult:
    """Write description, keywords and banner to the connected YouTube channel.

    Never raises: the outcome is stored on the channel and returned."""
    now = datetime.now(UTC)
    result = SyncResult(ok=False, at=now.isoformat(), manual=["Profilbild", "Links"])
    try:
        _sync(session, settings, redis, channel, result, client)
        result.ok = True
    except (ProfileSyncError, platform.PlatformError, QuotaExceededError) as exc:
        result.error = str(exc)[:300]
    except httpx.HTTPError as exc:
        result.error = f"YouTube nicht erreichbar ({type(exc).__name__})"
    except storage.StorageError:
        result.error = "Banner-Datei nicht gefunden"
    if not result.ok:
        result.applied = []  # nothing is saved before the final channels.update
    channel.strategy = {**(channel.strategy or {}), "profile_sync": result.as_dict()}
    session.flush()
    log.info(
        "profile sync",
        extra={"channel": channel.id, "ok": result.ok, "applied": result.applied},
    )
    return result


def _sync(
    session: Session,
    settings: Settings,
    redis: Redis,
    channel: Channel,
    result: SyncResult,
    client: httpx.Client | None,
) -> None:
    if channel.platform.code != PlatformCode.YOUTUBE:
        raise ProfileSyncError("Nur YouTube erlaubt das Profil über die Schnittstelle")
    if channel.auth_status != ChannelAuthStatus.AUTHORIZED or not channel.external_channel_id:
        raise ProfileSyncError("Kanal ist nicht verbunden")
    cred = session.scalar(
        select(ChannelCredential).where(ChannelCredential.channel_id == channel.id)
    )
    if cred is None:
        raise ProfileSyncError("Keine Zugangsdaten gespeichert")
    task = _task(session, channel)
    if task is None:
        # only channels made with the channel assistant: never overwrite the profile
        # of an existing channel that was connected later
        raise ProfileSyncError("Kanal stammt nicht aus dem Kanal-Assistenten")
    description = ((task.bio if task else None) or channel.description or "").strip()
    project = session.get(ContentProject, channel.content_project_id)
    words = keywords(channel, project)
    banner: bytes | None = None
    if task is not None and task.banner_uri:
        banner = storage.resolve(settings, task.banner_uri).read_bytes()
        if len(banner) > BANNER_MAX_BYTES:
            banner = None
    if not description and not words and banner is None:
        raise ProfileSyncError("Im Kanal-Assistenten ist noch nichts vorbereitet")
    quota.consume(redis, "youtube", UNITS, settings.youtube_daily_quota_units)
    token = youtube.access_token(session, settings, cred)
    headers = {"Authorization": f"Bearer {token}"}
    own = client is None
    http = client or youtube.http_client(60)
    try:
        current = _check(
            http.get(
                f"{youtube.API}/channels",
                params={"part": "brandingSettings", "id": channel.external_channel_id},
                headers=headers,
            ),
            "Lesen des Kanals",
        )
        items = current.get("items") or []
        if not items:
            raise ProfileSyncError("YouTube-Kanal nicht gefunden")
        branding: dict[str, Any] = dict(items[0].get("brandingSettings") or {})
        chan: dict[str, Any] = dict(branding.get("channel") or {})
        image: dict[str, Any] = dict(branding.get("image") or {})
        if banner is not None:
            uploaded = _check(
                http.post(
                    BANNER_UPLOAD_URL,
                    content=banner,
                    headers={**headers, "Content-Type": "image/png"},
                ),
                "Banner-Upload",
            )
            url = uploaded.get("url")
            if isinstance(url, str) and url:
                image["bannerExternalUrl"] = url
                result.applied.append("Banner")
        if description:
            chan["description"] = description[:DESCRIPTION_MAX]
            result.applied.append("Beschreibung")
        if words:
            chan["keywords"] = words
            result.applied.append("Stichwörter")
        chan.pop("title", None)  # unchanged title may be omitted; never change it
        body: dict[str, Any] = {
            "id": channel.external_channel_id,
            "brandingSettings": {"channel": chan, **({"image": image} if image else {})},
        }
        _check(
            http.put(
                f"{youtube.API}/channels",
                params={"part": "brandingSettings"},
                json=body,
                headers=headers,
            ),
            "Speichern des Profils",
        )
    finally:
        if own:
            http.close()
