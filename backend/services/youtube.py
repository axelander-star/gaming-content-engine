"""YouTube channel connection (OAuth 2.0) and upload (Phase 12).

Only documented, official endpoints (checked 14.11.2026, see
docs/API_INTEGRATIONS.md):

* OAuth: ``https://accounts.google.com/o/oauth2/v2/auth`` with
  ``access_type=offline`` and ``prompt=consent``; tokens from
  ``https://oauth2.googleapis.com/token``; revoke at
  ``https://oauth2.googleapis.com/revoke``.
* Channel of the connected account: ``GET /youtube/v3/channels?part=snippet&mine=true``
  (1 quota unit).
* Upload: resumable ``videos.insert``
  (``POST https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable``,
  then ``PUT`` of the file; 308/5xx resume, 404 restart). ``videos.insert`` has its
  own bucket of 100 calls per day.

Tokens are stored encrypted (:mod:`core.crypto`). Every HTTP call goes through
:func:`http_client`, which tests replace with a mock transport; tests never reach
Google.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import crypto
from core.config import Settings
from models.channels import Channel, ChannelCredential

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - endpoint, not a secret
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
SCOPES = (
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
)
UPLOAD_SCOPE = SCOPES[0]
PROVIDER = "youtube"
GAMING_CATEGORY = "20"
STATE_TTL = timedelta(minutes=10)
RETRY_STATUSES = {500, 502, 503, 504}

#: Replaced by tests with ``httpx.MockTransport``; ``None`` = real network.
TRANSPORT: httpx.BaseTransport | None = None


class YouTubeError(RuntimeError):
    """Permanent error from YouTube (bad request, forbidden, …)."""

    def __init__(self, message: str, status: int | None = None, reason: str | None = None):
        super().__init__(message)
        self.status = status
        self.reason = reason


class AuthExpiredError(YouTubeError):
    """The refresh token is no longer valid; the channel must be connected again."""


class TransientError(YouTubeError):
    """Temporary problem (5xx, network); the upload may be tried again later."""


class NotConfiguredError(RuntimeError):
    """No OAuth client configured (``YOUTUBE_OAUTH_CLIENT_ID``)."""


def http_client(timeout: float = 60.0) -> httpx.Client:
    return httpx.Client(transport=TRANSPORT, timeout=timeout)


def _client_id(settings: Settings) -> str:
    if not settings.youtube_oauth_client_id or not settings.youtube_oauth_client_secret:
        raise NotConfiguredError("YouTube-OAuth-Client ist nicht eingerichtet")
    return settings.youtube_oauth_client_id


# --- OAuth --------------------------------------------------------------------------


def make_state(settings: Settings, channel_id: int, user_id: int) -> str:
    now = datetime.now(UTC)
    payload = {"ch": channel_id, "u": user_id, "p": PROVIDER, "iat": now, "exp": now + STATE_TTL}
    return jwt.encode(payload, settings.secret_key.get_secret_value(), algorithm="HS256")


def read_state(settings: Settings, state: str) -> tuple[int, int]:
    """Channel and user id from a state issued by :func:`make_state` (signed, 10 min)."""
    try:
        data = jwt.decode(state, settings.secret_key.get_secret_value(), algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise YouTubeError("Ungültiger oder abgelaufener Anmeldevorgang") from exc
    if data.get("p") != PROVIDER:
        raise YouTubeError("Ungültiger Anmeldevorgang")
    return int(data["ch"]), int(data["u"])


def authorization_url(settings: Settings, state: str) -> str:
    params = {
        "client_id": _client_id(settings),
        "redirect_uri": settings.youtube_oauth_redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _token_request(settings: Settings, data: dict[str, str]) -> dict[str, Any]:
    body = {
        **data,
        "client_id": _client_id(settings),
        "client_secret": settings.youtube_oauth_client_secret.get_secret_value(),
    }
    with http_client(30) as client:
        try:
            res = client.post(TOKEN_URL, data=body)
        except httpx.HTTPError as exc:
            raise TransientError(f"Google nicht erreichbar: {type(exc).__name__}") from exc
    payload = _json(res)
    if res.status_code >= 400:
        error = str(payload.get("error", res.status_code))
        if error == "invalid_grant":
            raise AuthExpiredError("Zugriff abgelaufen oder widerrufen", res.status_code, error)
        if res.status_code >= 500:
            raise TransientError(f"Google-Fehler {res.status_code}", res.status_code, error)
        raise YouTubeError(f"Anmeldung abgelehnt ({error})", res.status_code, error)
    return payload


def _json(res: httpx.Response) -> dict[str, Any]:
    try:
        data = res.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _store_tokens(
    settings: Settings, cred: ChannelCredential, tokens: dict[str, Any], now: datetime
) -> None:
    cred.access_token_enc = crypto.encrypt(settings, str(tokens["access_token"]))
    if tokens.get("refresh_token"):
        cred.refresh_token_enc = crypto.encrypt(settings, str(tokens["refresh_token"]))
    cred.expires_at = now + timedelta(seconds=int(tokens.get("expires_in", 3600)))
    if tokens.get("scope"):
        cred.scopes = str(tokens["scope"]).split()
    cred.last_refreshed_at = now
    cred.last_error = None


def connect(
    session: Session, settings: Settings, channel: Channel, code: str, user_id: int
) -> ChannelCredential:
    """Exchange the authorization code, read the account's channel, store encrypted."""
    tokens = _token_request(
        settings,
        {
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": settings.youtube_oauth_redirect_uri,
        },
    )
    if not tokens.get("refresh_token"):
        raise YouTubeError("Google hat keinen Refresh-Token geliefert; bitte erneut verbinden")
    now = datetime.now(UTC)
    cred = session.scalar(
        select(ChannelCredential).where(ChannelCredential.channel_id == channel.id)
    ) or ChannelCredential(channel_id=channel.id, provider=PROVIDER)
    _store_tokens(settings, cred, tokens, now)
    cred.connected_by_user_id = user_id
    account = own_channel(str(tokens["access_token"]))
    cred.external_account_id = account.get("id")
    cred.external_account_name = (account.get("snippet") or {}).get("title")
    session.add(cred)
    return cred


def own_channel(access_token: str) -> dict[str, Any]:
    """The YouTube channel of the connected account (``channels.list mine=true``)."""
    with http_client(30) as client:
        res = client.get(
            f"{API}/channels",
            params={"part": "snippet", "mine": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if res.status_code >= 400:
        raise YouTubeError(f"Kanal nicht lesbar ({res.status_code})", res.status_code)
    items = _json(res).get("items") or []
    if not items:
        raise YouTubeError("Zu diesem Google-Konto gibt es keinen YouTube-Kanal")
    return dict(items[0])


def access_token(session: Session, settings: Settings, cred: ChannelCredential) -> str:
    """A valid access token; refreshes it shortly before it expires."""
    now = datetime.now(UTC)
    if cred.access_token_enc and cred.expires_at and cred.expires_at > now + timedelta(minutes=2):
        return crypto.decrypt(settings, cred.access_token_enc)
    if not cred.refresh_token_enc:
        raise AuthExpiredError("Kein Refresh-Token gespeichert")
    refresh = crypto.decrypt(settings, cred.refresh_token_enc)
    tokens = _token_request(settings, {"grant_type": "refresh_token", "refresh_token": refresh})
    _store_tokens(settings, cred, tokens, now)
    return str(tokens["access_token"])


def revoke(settings: Settings, cred: ChannelCredential) -> bool:
    """Best effort: revoke the refresh token at Google."""
    token_enc = cred.refresh_token_enc or cred.access_token_enc
    if not token_enc:
        return False
    try:
        token = crypto.decrypt(settings, token_enc)
        with http_client(15) as client:
            res = client.post(REVOKE_URL, data={"token": token})
        return res.status_code == 200
    except (httpx.HTTPError, crypto.CredentialError):
        return False


# --- upload -------------------------------------------------------------------------


@dataclass(frozen=True)
class UploadResult:
    video_id: str
    privacy: str
    url: str


def video_resource(
    title: str,
    description: str,
    language: str,
    privacy: str,
    synthetic_voice: bool,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags or [],
            "categoryId": GAMING_CATEGORY,
            "defaultLanguage": language,
            "defaultAudioLanguage": language,
        },
        "status": {
            "privacyStatus": privacy,  # always explicit: the API default is public
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": synthetic_voice,
        },
    }


def _raise_for(res: httpx.Response, where: str) -> None:
    if res.status_code in RETRY_STATUSES:
        raise TransientError(f"{where}: YouTube {res.status_code}", res.status_code)
    errors = (_json(res).get("error") or {}).get("errors") or [{}]
    reason = str(errors[0].get("reason") or "")
    if res.status_code == 401:
        raise AuthExpiredError(f"{where}: nicht angemeldet", 401, reason)
    if reason in ("quotaExceeded", "uploadLimitExceeded", "rateLimitExceeded"):
        raise TransientError(f"{where}: Kontingent erschöpft ({reason})", res.status_code, reason)
    raise YouTubeError(
        f"{where}: YouTube {res.status_code} {reason}".strip(), res.status_code, reason
    )


def upload(
    token: str,
    path: Path,
    resource: dict[str, Any],
    attempts: int = 5,
    sleep: Any = time.sleep,
) -> UploadResult:
    """Resumable upload of ``path``; resumes after 5xx/network errors with backoff."""
    size = path.stat().st_size
    auth = {"Authorization": f"Bearer {token}"}
    with http_client(600) as client:
        session_url = _start_session(client, auth, size, resource)
        offset = 0
        for attempt in range(attempts):
            res: httpx.Response | None = None
            try:
                with path.open("rb") as fh:
                    fh.seek(offset)
                    headers = {
                        **auth,
                        "Content-Type": "video/mp4",
                        "Content-Length": str(size - offset),
                    }
                    if offset:
                        headers["Content-Range"] = f"bytes {offset}-{size - 1}/{size}"
                    res = client.put(session_url, content=fh.read(), headers=headers)
            except httpx.TransportError:
                res = None  # connection lost: ask for the status and resume
            if res is not None and res.status_code in (200, 201):
                return _finished(res)
            if res is not None and res.status_code == 404:  # session expired: start again
                session_url, offset = _start_session(client, auth, size, resource), 0
                continue
            if res is not None and res.status_code not in RETRY_STATUSES | {308}:
                _raise_for(res, "Upload")
            sleep(min(60, 2**attempt))
            offset, done = _uploaded(client, session_url, auth, size)
            if done is not None:
                return _finished(done)
        raise TransientError(f"Upload nach {attempts} Versuchen nicht abgeschlossen")


def _start_session(
    client: httpx.Client, auth: dict[str, str], size: int, resource: dict[str, Any]
) -> str:
    res = client.post(
        UPLOAD_URL,
        params={"uploadType": "resumable", "part": "snippet,status"},
        json=resource,
        headers={
            **auth,
            "X-Upload-Content-Length": str(size),
            "X-Upload-Content-Type": "video/mp4",
        },
    )
    if res.status_code != 200 or "location" not in res.headers:
        _raise_for(res, "Upload-Start")
        raise YouTubeError("Upload-Start ohne Upload-Adresse beantwortet")
    return res.headers["location"]


def _finished(res: httpx.Response) -> UploadResult:
    data = _json(res)
    vid = str(data.get("id") or "")
    if not vid:
        raise YouTubeError("Upload ohne Video-ID beantwortet")
    privacy = str((data.get("status") or {}).get("privacyStatus") or "")
    return UploadResult(vid, privacy, f"https://www.youtube.com/shorts/{vid}")


def _uploaded(
    client: httpx.Client, url: str, auth: dict[str, str], size: int
) -> tuple[int, httpx.Response | None]:
    """Bytes the server already has (``Content-Range: bytes */size`` → 308 + Range).

    Returns the final response instead if the upload turns out to be complete."""
    headers = {**auth, "Content-Length": "0", "Content-Range": f"bytes */{size}"}
    try:
        res = client.put(url, headers=headers)
    except httpx.TransportError:
        return 0, None
    if res.status_code in (200, 201):
        return size, res
    rng = res.headers.get("range")
    if res.status_code == 308 and rng and "-" in rng:
        return int(rng.split("-")[-1]) + 1, None
    return 0, None
