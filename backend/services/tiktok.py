"""TikTok connection (Login Kit, OAuth 2.0) and Direct Post (Phase 13).

Only documented, official endpoints (checked 14.11.2026, see
docs/API_INTEGRATIONS.md):

* OAuth: ``https://www.tiktok.com/v2/auth/authorize/``; tokens and refresh at
  ``https://open.tiktokapis.com/v2/oauth/token/`` (access 24 h, refresh 365 days,
  the refresh token may rotate); revoke at ``/v2/oauth/revoke/``.
* Content Posting API, scope ``video.publish``: ``creator_info/query`` (privacy
  options of the creator), ``video/init`` with ``FILE_UPLOAD``, chunked ``PUT`` to
  the returned ``upload_url`` (``Content-Range``), ``status/fetch``.

Posts of unaudited apps are restricted to private viewing; the default privacy
level here is ``SELF_ONLY`` and must be one the creator offers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import crypto
from core.config import Settings
from models.channels import Channel, ChannelCredential
from services import platform
from services.platform import AuthExpiredError, PlatformError, RestrictedError, TransientError

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
API = "https://open.tiktokapis.com/v2"
TOKEN_URL = f"{API}/oauth/token/"
REVOKE_URL = f"{API}/oauth/revoke/"
CREATOR_INFO_URL = f"{API}/post/publish/creator_info/query/"
INIT_URL = f"{API}/post/publish/video/init/"
STATUS_URL = f"{API}/post/publish/status/fetch/"
PUBLISH_SCOPE = "video.publish"
SCOPES = (PUBLISH_SCOPE,)
PROVIDER = "tiktok"

#: Files up to this size go in one request; larger ones in chunks (min 5 MB, max 64 MB
#: per chunk, the last chunk takes the remainder, at most 1000 chunks).
SINGLE_UPLOAD_MAX = 64_000_000
CHUNK_SIZE = 10_000_000

#: Error codes that mean "later again" (rate limits, daily caps, server errors).
TRANSIENT_CODES = {
    "rate_limit_exceeded",
    "spam_risk_too_many_posts",
    "reached_active_user_cap",
    "internal_error",
}
AUTH_CODES = {"access_token_invalid", "scope_not_authorized", "scope_permission_missed"}
RESTRICTED_CODES = {
    "unaudited_client_can_only_post_to_private_accounts",
    "spam_risk_user_banned_from_posting",
}


def _client(settings: Settings) -> tuple[str, str]:
    if not settings.tiktok_client_key or not settings.tiktok_client_secret.get_secret_value():
        raise platform.NotConfiguredError("TikTok-App ist nicht eingerichtet")
    return settings.tiktok_client_key, settings.tiktok_client_secret.get_secret_value()


# --- OAuth --------------------------------------------------------------------------


def authorization_url(settings: Settings, state: str) -> str:
    key, _ = _client(settings)
    params = {
        "client_key": key,
        "scope": ",".join(SCOPES),
        "response_type": "code",
        "redirect_uri": settings.tiktok_oauth_redirect_uri,
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _token_request(settings: Settings, data: dict[str, str]) -> dict[str, Any]:
    key, secret = _client(settings)
    body = {**data, "client_key": key, "client_secret": secret}
    with platform.http_client(30) as client:
        try:
            res = client.post(TOKEN_URL, data=body)
        except httpx.HTTPError as exc:
            raise TransientError(f"TikTok nicht erreichbar: {type(exc).__name__}") from exc
    payload = platform.json_of(res)
    if res.status_code >= 500:
        raise TransientError(f"TikTok-Fehler {res.status_code}", res.status_code)
    if res.status_code >= 400 or "access_token" not in payload:
        error = str(payload.get("error") or res.status_code)
        if data.get("grant_type") == "refresh_token":
            raise AuthExpiredError(
                "TikTok-Zugang abgelaufen oder widerrufen", res.status_code, error
            )
        raise PlatformError(f"TikTok-Anmeldung abgelehnt ({error})", res.status_code, error)
    return payload


def _store_tokens(
    settings: Settings, cred: ChannelCredential, tokens: dict[str, Any], now: datetime
) -> None:
    cred.access_token_enc = crypto.encrypt(settings, str(tokens["access_token"]))
    if tokens.get("refresh_token"):  # may rotate: always keep the newest one
        cred.refresh_token_enc = crypto.encrypt(settings, str(tokens["refresh_token"]))
    cred.expires_at = now + timedelta(seconds=int(tokens.get("expires_in", 86400)))
    if tokens.get("scope"):
        cred.scopes = [s for s in str(tokens["scope"]).split(",") if s]
    cred.last_refreshed_at = now
    cred.last_error = None


def connect(
    session: Session, settings: Settings, channel: Channel, code: str, user_id: int
) -> ChannelCredential:
    """Exchange the code, read the creator, store the tokens encrypted."""
    tokens = _token_request(
        settings,
        {
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": settings.tiktok_oauth_redirect_uri,
        },
    )
    now = datetime.now(UTC)
    cred = session.scalar(
        select(ChannelCredential).where(ChannelCredential.channel_id == channel.id)
    ) or ChannelCredential(channel_id=channel.id, provider=PROVIDER)
    cred.provider = PROVIDER
    _store_tokens(settings, cred, tokens, now)
    cred.connected_by_user_id = user_id
    cred.external_account_id = str(tokens.get("open_id") or "") or None
    if PUBLISH_SCOPE in (cred.scopes or []):
        info = creator_info(str(tokens["access_token"]))
        cred.external_account_name = info.get("creator_username")
    session.add(cred)
    return cred


def access_token(session: Session, settings: Settings, cred: ChannelCredential) -> str:
    now = datetime.now(UTC)
    if cred.access_token_enc and cred.expires_at and cred.expires_at > now + timedelta(minutes=5):
        return crypto.decrypt(settings, cred.access_token_enc)
    if not cred.refresh_token_enc:
        raise AuthExpiredError("Kein TikTok-Refresh-Token gespeichert")
    refresh = crypto.decrypt(settings, cred.refresh_token_enc)
    tokens = _token_request(settings, {"grant_type": "refresh_token", "refresh_token": refresh})
    _store_tokens(settings, cred, tokens, now)
    return str(tokens["access_token"])


def revoke(settings: Settings, cred: ChannelCredential) -> bool:
    """Best effort: revoke the access token at TikTok."""
    if not cred.access_token_enc:
        return False
    try:
        key, secret = _client(settings)
        token = crypto.decrypt(settings, cred.access_token_enc)
        with platform.http_client(15) as client:
            res = client.post(
                REVOKE_URL, data={"client_key": key, "client_secret": secret, "token": token}
            )
        return res.status_code == 200
    except (httpx.HTTPError, crypto.CredentialError, platform.NotConfiguredError):
        return False


# --- Content Posting API ------------------------------------------------------------


def _check(res: httpx.Response, where: str) -> dict[str, Any]:
    """``data`` of a Content Posting response, or the matching error.

    TikTok reports some errors (e.g. ``spam_risk_too_many_posts``) with HTTP 200, so
    the ``error.code`` field decides, not only the status."""
    payload = platform.json_of(res)
    code = str((payload.get("error") or {}).get("code") or "")
    if res.status_code < 400 and code in ("", "ok"):
        return dict(payload.get("data") or {})
    message = f"{where}: TikTok {res.status_code} {code}".strip()
    if res.status_code >= 500 or res.status_code == 429 or code in TRANSIENT_CODES:
        raise TransientError(message, res.status_code, code)
    if res.status_code == 401 or code in AUTH_CODES:
        raise AuthExpiredError(message, res.status_code, code)
    if code in RESTRICTED_CODES:
        raise RestrictedError(message, res.status_code, code)
    raise PlatformError(message, res.status_code, code)


def _post(url: str, token: str, body: dict[str, Any] | None, where: str) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
    }
    with platform.http_client(30) as client:
        try:
            res = (
                client.post(url, json=body, headers=headers)
                if body is not None
                else (client.post(url, headers=headers))
            )
        except httpx.HTTPError as exc:
            raise TransientError(f"{where}: TikTok nicht erreichbar") from exc
    return _check(res, where)


def creator_info(token: str) -> dict[str, Any]:
    return _post(CREATOR_INFO_URL, token, None, "Creator-Info")


def chunk_plan(size: int) -> tuple[int, int]:
    """``(chunk_size, total_chunk_count)`` per the media transfer guide."""
    if size <= SINGLE_UPLOAD_MAX:
        return size, 1
    return CHUNK_SIZE, size // CHUNK_SIZE  # the last chunk takes the remainder


def chunk_ranges(size: int) -> list[tuple[int, int]]:
    chunk, count = chunk_plan(size)
    ranges = [(i * chunk, (i + 1) * chunk - 1) for i in range(count)]
    ranges[-1] = (ranges[-1][0], size - 1)
    return ranges


@dataclass(frozen=True)
class PostResult:
    publish_id: str
    status: str
    post_id: str | None
    privacy: str
    username: str | None

    @property
    def url(self) -> str | None:
        if self.post_id and self.username:
            return f"https://www.tiktok.com/@{self.username}/video/{self.post_id}"
        return None


def post_video(
    token: str,
    path: Path,
    title: str,
    privacy: str,
    ai_generated: bool,
    attempts: int = 5,
    polls: int = 10,
    interval: float = 30.0,
    sleep: Any = time.sleep,
) -> PostResult:
    """Direct Post of ``path``: creator check, init, chunked upload, status."""
    info = creator_info(token)
    options = [str(o) for o in info.get("privacy_level_options") or []]
    if privacy not in options:
        raise RestrictedError(
            f"Sichtbarkeit {privacy} ist für dieses Konto nicht erlaubt "
            f"(möglich: {', '.join(options) or 'keine'})"
        )
    size = path.stat().st_size
    chunk, count = chunk_plan(size)
    body = {
        "post_info": {
            "title": title[:2200],
            "privacy_level": privacy,
            "disable_duet": bool(info.get("duet_disabled")),
            "disable_stitch": bool(info.get("stitch_disabled")),
            "disable_comment": bool(info.get("comment_disabled")),
            "brand_content_toggle": False,
            "brand_organic_toggle": False,
            "is_aigc": ai_generated,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": size,
            "chunk_size": chunk,
            "total_chunk_count": count,
        },
    }
    data = _post(INIT_URL, token, body, "Upload-Start")
    publish_id, upload_url = str(data.get("publish_id") or ""), str(data.get("upload_url") or "")
    if not publish_id or not upload_url:
        raise PlatformError("Upload-Start ohne publish_id oder upload_url beantwortet")
    _upload_chunks(upload_url, path, size, attempts, sleep)
    status, post_id = _wait(token, publish_id, polls, interval, sleep)
    return PostResult(publish_id, status, post_id, privacy, info.get("creator_username"))


def _upload_chunks(url: str, path: Path, size: int, attempts: int, sleep: Any) -> None:
    with platform.http_client(600) as client, path.open("rb") as fh:
        for first, last in chunk_ranges(size):
            fh.seek(first)
            payload = fh.read(last - first + 1)
            headers = {
                "Content-Type": "video/mp4",
                "Content-Length": str(len(payload)),
                "Content-Range": f"bytes {first}-{last}/{size}",
            }
            for attempt in range(attempts):
                try:
                    res = client.put(url, content=payload, headers=headers)
                except httpx.TransportError:
                    res = None
                if res is not None and res.status_code in (200, 201, 206):
                    break
                if res is not None and res.status_code < 500:
                    raise PlatformError(f"Upload: TikTok {res.status_code}", res.status_code)
                sleep(min(60, 2**attempt))
            else:
                raise TransientError(f"Upload nach {attempts} Versuchen nicht abgeschlossen")


def _wait(
    token: str, publish_id: str, polls: int, interval: float, sleep: Any
) -> tuple[str, str | None]:
    """Status after the upload. ``PUBLISH_COMPLETE`` may come without a post id: TikTok
    only reveals it for public posts that passed moderation."""
    status = "PROCESSING_UPLOAD"
    for i in range(max(1, polls)):
        if i:
            sleep(interval)
        data = _post(STATUS_URL, token, {"publish_id": publish_id}, "Status")
        status = str(data.get("status") or status)
        if status == "FAILED":
            raise PlatformError(f"TikTok hat den Beitrag abgelehnt: {data.get('fail_reason')}")
        if status == "PUBLISH_COMPLETE":
            ids = data.get("publicaly_available_post_id") or []  # spelling as in the API
            return status, (str(ids[0]) if ids else None)
    return status, None  # still processing: uploaded, TikTok finishes on its own
