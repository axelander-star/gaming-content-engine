"""Instagram Reels and Facebook Page Reels via Meta's Graph API (Phase 13).

One Meta app ("Facebook Login for Business") serves both platforms. Only
documented, official endpoints (Graph API v25.0, checked 14.11.2026, see
docs/API_INTEGRATIONS.md):

* Login: ``https://www.facebook.com/v25.0/dialog/oauth``; code → token at
  ``/oauth/access_token``; long-lived user token with ``fb_exchange_token``; Page
  tokens from ``/{user-id}/accounts`` (tasks must include ``CREATE_CONTENT``).
* Instagram: ``POST /{ig-user-id}/media`` (``media_type=REELS``,
  ``upload_type=resumable``) → upload to ``rupload.facebook.com/ig-api-upload`` →
  ``status_code`` until ``FINISHED`` → ``POST /{ig-user-id}/media_publish``;
  ``content_publishing_limit`` before each post.
* Facebook: ``POST /{page-id}/video_reels`` ``upload_phase=start`` → upload to
  ``rupload.facebook.com/video-upload`` → ``upload_phase=finish`` with
  ``video_state=PUBLISHED``; ``GET /{video-id}?fields=status``.

Reels on Pages and Instagram have no private mode: a live post is public. Tests
use :data:`services.platform.TRANSPORT` and never reach Meta.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import crypto
from core.config import Settings
from core.enums import PlatformCode
from models.channels import Channel, ChannelCredential
from services import platform
from services.platform import AuthExpiredError, PlatformError, TransientError

VERSION = "v25.0"
GRAPH = f"https://graph.facebook.com/{VERSION}"
DIALOG_URL = f"https://www.facebook.com/{VERSION}/dialog/oauth"
RUPLOAD = "https://rupload.facebook.com"
PROVIDER = "meta"

FACEBOOK_SCOPES = (
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_posts",
    "read_insights",  # statistics (Phase 14)
    "pages_manage_engagement",  # required by video_insights (Phase 14)
)
INSTAGRAM_SCOPES = (
    "instagram_basic",
    "instagram_content_publish",
    "instagram_manage_insights",  # statistics (Phase 14)
    "pages_show_list",
    "pages_read_engagement",
)
PUBLISH_SCOPE = {
    PlatformCode.FACEBOOK: "pages_manage_posts",
    PlatformCode.INSTAGRAM: "instagram_content_publish",
}
#: Graph error codes for an invalid/expired token, and for throttling.
AUTH_CODES = {190}
THROTTLE_CODES = {4, 17, 32, 613}


def scopes_for(platform_code: PlatformCode) -> tuple[str, ...]:
    return INSTAGRAM_SCOPES if platform_code == PlatformCode.INSTAGRAM else FACEBOOK_SCOPES


def _app(settings: Settings) -> tuple[str, str]:
    if not settings.meta_app_id or not settings.meta_app_secret.get_secret_value():
        raise platform.NotConfiguredError("Meta-App ist nicht eingerichtet")
    return settings.meta_app_id, settings.meta_app_secret.get_secret_value()


def _check(res: httpx.Response, where: str) -> dict[str, Any]:
    payload = platform.json_of(res)
    if res.status_code < 400 and "error" not in payload:
        return payload
    err = payload.get("error") or {}
    code = int(err.get("code") or 0)
    message = f"{where}: Meta {res.status_code} {err.get('message') or ''}".strip()
    if res.status_code >= 500 or code in THROTTLE_CODES or err.get("is_transient"):
        raise TransientError(message, res.status_code, str(code))
    if code in AUTH_CODES:
        raise AuthExpiredError(message, res.status_code, str(code))
    raise PlatformError(message, res.status_code, str(code))


def _get(path: str, params: dict[str, Any], where: str) -> dict[str, Any]:
    with platform.http_client(30) as client:
        try:
            res = client.get(f"{GRAPH}/{path}", params=params)
        except httpx.HTTPError as exc:
            raise TransientError(f"{where}: Meta nicht erreichbar") from exc
    return _check(res, where)


def _post(path: str, params: dict[str, Any], where: str) -> dict[str, Any]:
    with platform.http_client(60) as client:
        try:
            res = client.post(f"{GRAPH}/{path}", params=params)
        except httpx.HTTPError as exc:
            raise TransientError(f"{where}: Meta nicht erreichbar") from exc
    return _check(res, where)


# --- login --------------------------------------------------------------------------


def authorization_url(settings: Settings, state: str, platform_code: PlatformCode) -> str:
    app_id, _ = _app(settings)
    params = {
        "client_id": app_id,
        "redirect_uri": settings.meta_oauth_redirect_uri,
        "state": state,
        "response_type": "code",
        "scope": ",".join(scopes_for(platform_code)),
    }
    return f"{DIALOG_URL}?{urlencode(params)}"


def _user_token(settings: Settings, code: str) -> str:
    app_id, secret = _app(settings)
    short = _get(
        "oauth/access_token",
        {
            "client_id": app_id,
            "client_secret": secret,
            "redirect_uri": settings.meta_oauth_redirect_uri,
            "code": code,
        },
        "Anmeldung",
    )
    long = _get(
        "oauth/access_token",
        {
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": secret,
            "fb_exchange_token": str(short.get("access_token") or ""),
        },
        "Langzeit-Token",
    )
    token = str(long.get("access_token") or "")
    if not token:
        raise PlatformError("Meta hat keinen Zugangsschlüssel geliefert")
    return token


@dataclass(frozen=True)
class Target:
    """The account a channel publishes to: a Page, or the Instagram account of a Page."""

    account_id: str
    name: str
    page_token: str


def pick_target(pages: list[dict[str, Any]], platform_code: PlatformCode) -> Target:
    """Exactly one granted Page (with ``CREATE_CONTENT``; for Instagram with a linked
    professional account) must fit, so a channel can never post to the wrong account."""
    fitting = []
    for page in pages:
        if "CREATE_CONTENT" not in (page.get("tasks") or []) or not page.get("access_token"):
            continue
        if platform_code == PlatformCode.INSTAGRAM:
            ig = page.get("instagram_business_account") or {}
            if ig.get("id"):
                name = f"@{ig['username']}" if ig.get("username") else str(ig["id"])
                fitting.append(Target(str(ig["id"]), name, str(page["access_token"])))
        else:
            fitting.append(
                Target(
                    str(page["id"]), str(page.get("name") or page["id"]), str(page["access_token"])
                )
            )
    if not fitting:
        what = (
            "Instagram-Profikonto an einer Seite"
            if platform_code == PlatformCode.INSTAGRAM
            else "Facebook-Seite mit Veröffentlichungsrecht"
        )
        raise PlatformError(f"Keine {what} freigegeben")
    if len(fitting) > 1:
        raise PlatformError(
            "Mehrere Seiten freigegeben; bitte beim Verbinden nur die Seite dieses Kanals auswählen"
        )
    return fitting[0]


def connect(
    session: Session, settings: Settings, channel: Channel, code: str, user_id: int
) -> ChannelCredential:
    """Code → long-lived user token → the one fitting Page token; stored encrypted."""
    platform_code = PlatformCode(channel.platform.code)
    user_token = _user_token(settings, code)
    me = _get("me", {"fields": "id", "access_token": user_token}, "Konto")
    pages = _get(
        f"{me['id']}/accounts",
        {
            "fields": "id,name,access_token,tasks,instagram_business_account{id,username}",
            "access_token": user_token,
        },
        "Seiten",
    )
    target = pick_target(list(pages.get("data") or []), platform_code)
    perms = _get("me/permissions", {"access_token": user_token}, "Berechtigungen")
    granted = [
        str(p["permission"]) for p in perms.get("data") or [] if p.get("status") == "granted"
    ]
    cred = session.scalar(
        select(ChannelCredential).where(ChannelCredential.channel_id == channel.id)
    ) or ChannelCredential(channel_id=channel.id, provider=PROVIDER)
    cred.provider = PROVIDER
    cred.access_token_enc = crypto.encrypt(settings, target.page_token)
    cred.refresh_token_enc = None  # Page tokens from a long-lived user token do not expire
    cred.expires_at = None
    cred.scopes = granted
    cred.external_account_id = target.account_id
    cred.external_account_name = target.name
    cred.connected_by_user_id = user_id
    cred.last_refreshed_at = datetime.now(UTC)
    cred.last_error = None
    session.add(cred)
    return cred


def page_token(settings: Settings, cred: ChannelCredential) -> str:
    if not cred.access_token_enc:
        raise AuthExpiredError("Kein Meta-Zugangsschlüssel gespeichert")
    return crypto.decrypt(settings, cred.access_token_enc)


# --- upload to rupload.facebook.com --------------------------------------------------


def _rupload(url: str, token: str, path: Path, offset: int) -> httpx.Response | None:
    size = path.stat().st_size
    with platform.http_client(600) as client, path.open("rb") as fh:
        fh.seek(offset)
        try:
            return client.post(
                url,
                content=fh.read(),
                headers={
                    "Authorization": f"OAuth {token}",
                    "offset": str(offset),
                    "file_size": str(size),
                    "Content-Type": "application/octet-stream",
                },
            )
        except httpx.TransportError:
            return None


@dataclass(frozen=True)
class ReelResult:
    external_id: str
    url: str | None
    status: str


# --- Instagram ----------------------------------------------------------------------


def publish_instagram(
    token: str,
    ig_user_id: str,
    path: Path,
    caption: str,
    attempts: int = 5,
    polls: int = 10,
    interval: float = 30.0,
    sleep: Any = time.sleep,
) -> ReelResult:
    limit = _get(
        f"{ig_user_id}/content_publishing_limit",
        {"fields": "quota_usage,config", "access_token": token},
        "Kontingent",
    )
    usage = (limit.get("data") or [{}])[0]
    total = int((usage.get("config") or {}).get("quota_total") or 0)
    if total and int(usage.get("quota_usage") or 0) >= total:
        raise TransientError(f"Instagram: Tageskontingent von {total} Beiträgen erreicht")
    container = _post(
        f"{ig_user_id}/media",
        {
            "media_type": "REELS",
            "upload_type": "resumable",
            "caption": caption[:2200],
            "access_token": token,
        },
        "Container",
    )
    cid, uri = str(container.get("id") or ""), str(container.get("uri") or "")
    if not cid or not uri:
        raise PlatformError("Container ohne id oder Upload-Adresse beantwortet")
    for attempt in range(attempts):
        res = _rupload(uri, token, path, 0)
        if res is not None and res.status_code < 400:
            break
        if res is not None and res.status_code < 500:
            _check(res, "Upload")
        sleep(min(60, 2**attempt))
    else:
        raise TransientError(f"Upload nach {attempts} Versuchen nicht abgeschlossen")
    for i in range(max(1, polls)):
        if i:
            sleep(interval)
        status = str(_get(cid, {"fields": "status_code,status", "access_token": token}, "Status")
                     .get("status_code") or "")  # fmt: skip
        if status in ("ERROR", "EXPIRED"):
            raise PlatformError(f"Instagram hat das Video nicht verarbeitet ({status})")
        if status == "FINISHED":
            break
    else:
        raise TransientError("Instagram verarbeitet das Video noch; später erneut")
    media = _post(
        f"{ig_user_id}/media_publish",
        {"creation_id": cid, "access_token": token},
        "Veröffentlichen",
    )
    media_id = str(media.get("id") or "")
    if not media_id:
        raise PlatformError("Veröffentlichung ohne Medien-ID beantwortet")
    try:  # the permalink is a convenience; the post exists either way
        url = _get(media_id, {"fields": "permalink", "access_token": token}, "Link").get(
            "permalink"
        )
    except PlatformError:
        url = None
    return ReelResult(media_id, str(url) if url else None, "PUBLISHED")


# --- Facebook -----------------------------------------------------------------------


def publish_facebook(
    token: str,
    page_id: str,
    path: Path,
    description: str,
    title: str,
    attempts: int = 5,
    polls: int = 10,
    interval: float = 30.0,
    sleep: Any = time.sleep,
) -> ReelResult:
    start = _post(
        f"{page_id}/video_reels", {"upload_phase": "start", "access_token": token}, "Upload-Start"
    )
    video_id = str(start.get("video_id") or "")
    if not video_id:
        raise PlatformError("Upload-Start ohne video_id beantwortet")
    url = f"{RUPLOAD}/video-upload/{VERSION}/{video_id}"
    offset = 0
    for attempt in range(attempts):
        res = _rupload(url, token, path, offset)
        if res is not None and res.status_code < 400:
            break
        if res is not None and res.status_code < 500:
            _check(res, "Upload")
        sleep(min(60, 2**attempt))
        phase = _status(token, video_id).get("uploading_phase") or {}
        offset = int(phase.get("bytes_transfered") or 0)  # spelling as in the API
    else:
        raise TransientError(f"Upload nach {attempts} Versuchen nicht abgeschlossen")
    _post(
        f"{page_id}/video_reels",
        {
            "upload_phase": "finish",
            "video_id": video_id,
            "video_state": "PUBLISHED",
            "description": description,
            "title": title,
            "access_token": token,
        },
        "Veröffentlichen",
    )
    state = "processing"
    for i in range(max(1, polls)):
        if i:
            sleep(interval)
        status = _status(token, video_id)
        error = (status.get("processing_phase") or {}).get("error")
        if error:
            raise PlatformError(f"Facebook hat das Video abgelehnt: {error.get('message')}")
        if (status.get("publishing_phase") or {}).get("status") == "complete":
            state = "complete"
            break
    return ReelResult(video_id, None, state)


def _status(token: str, video_id: str) -> dict[str, Any]:
    data = _get(video_id, {"fields": "status", "access_token": token}, "Status")
    return dict(data.get("status") or {})
