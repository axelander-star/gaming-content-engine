"""Instagram API with Instagram Login (extension E8): Reels without a Facebook Page.

Checked against the official Meta documentation on 15.11.2026 (details and the
parts that could not be re-checked automatically: docs/API_INTEGRATIONS.md):

* Login: ``https://api.instagram.com/oauth/authorize`` with ``client_id``,
  ``redirect_uri``, ``response_type=code``, comma-separated ``scope``, ``state``.
  Meta appends ``#_`` to the redirect; it is not part of the code. Codes are valid
  for one hour and can be used once.
* Scopes: ``instagram_business_basic`` and ``instagram_business_content_publish``.
* Code → short-lived token at ``https://api.instagram.com/oauth/access_token``,
  long-lived token (60 days) via ``graph.instagram.com/access_token``
  (``grant_type=ig_exchange_token``), renewal via
  ``graph.instagram.com/refresh_access_token`` (``grant_type=ig_refresh_token``).
* Account: ``GET graph.instagram.com/v25.0/me``.
* Publishing: ``POST /<IG_ID>/media`` with ``media_type=REELS`` and ``video_url``
  (Meta fetches the file; the resumable upload is only for Facebook Login apps),
  ``GET /<container>?fields=status_code`` until ``FINISHED``,
  ``POST /<IG_ID>/media_publish`` with ``creation_id``.
  At most 100 API posts per 24 hours; checked via ``content_publishing_limit``.

Tests use :data:`services.platform.TRANSPORT` and never reach Instagram.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import crypto
from core.config import Settings
from models.channels import Channel, ChannelCredential
from services import platform
from services.meta import ReelResult
from services.meta import _check as check_graph
from services.platform import AuthExpiredError, PlatformError, TransientError

VERSION = "v25.0"
AUTH_URL = "https://api.instagram.com/oauth/authorize"
TOKEN_URL = "https://api.instagram.com/oauth/access_token"  # noqa: S105 - endpoint
GRAPH_ROOT = "https://graph.instagram.com"
GRAPH = f"{GRAPH_ROOT}/{VERSION}"
PROVIDER = "instagram"
PUBLISH_SCOPE = "instagram_business_content_publish"
SCOPES = ("instagram_business_basic", PUBLISH_SCOPE)
#: Renew the 60-day token when it has less than this left (and is older than 24 h).
REFRESH_BEFORE = timedelta(days=7)
MIN_TOKEN_AGE = timedelta(hours=24)


def _app(settings: Settings) -> tuple[str, str]:
    if not settings.instagram_app_id or not settings.instagram_app_secret.get_secret_value():
        raise platform.NotConfiguredError("Instagram-App ist nicht eingerichtet")
    return settings.instagram_app_id, settings.instagram_app_secret.get_secret_value()


def authorization_url(settings: Settings, state: str) -> str:
    app_id, _ = _app(settings)
    params = {
        "client_id": app_id,
        "redirect_uri": settings.instagram_oauth_redirect_uri,
        "response_type": "code",
        "scope": ",".join(SCOPES),
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _request(method: str, url: str, where: str, **kwargs: Any) -> dict[str, Any]:
    with platform.http_client(60) as client:
        try:
            res = client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise TransientError(f"{where}: Instagram nicht erreichbar") from exc
    try:
        return check_graph(res, where)
    except PlatformError as exc:
        # The token endpoint answers OAuth errors without the Graph error object.
        payload = platform.json_of(res)
        if res.status_code in (400, 401) and payload.get("error_type") == "OAuthException":
            raise AuthExpiredError(f"{where}: {payload.get('error_message') or ''}") from exc
        raise


def _get(path: str, params: dict[str, Any], where: str) -> dict[str, Any]:
    return _request("GET", f"{GRAPH}/{path}", where, params=params)


def _post(path: str, params: dict[str, Any], where: str) -> dict[str, Any]:
    return _request("POST", f"{GRAPH}/{path}", where, params=params)


def _short_token(settings: Settings, code: str) -> tuple[str, list[str]]:
    app_id, secret = _app(settings)
    data = _request(
        "POST",
        TOKEN_URL,
        "Anmeldung",
        data={
            "client_id": app_id,
            "client_secret": secret,
            "grant_type": "authorization_code",
            "redirect_uri": settings.instagram_oauth_redirect_uri,
            "code": code.removesuffix("#_"),
        },
    )
    # The answer is either flat or wrapped in "data" (both forms appear in Meta's docs).
    row = (data.get("data") or [data])[0] if isinstance(data.get("data"), list) else data
    token = str(row.get("access_token") or "")
    if not token:
        raise PlatformError("Instagram hat keinen Zugangsschlüssel geliefert")
    perms = row.get("permissions") or []
    scopes = perms.split(",") if isinstance(perms, str) else [str(p) for p in perms]
    return token, [s.strip() for s in scopes if s.strip()]


def _long_token(settings: Settings, short: str) -> tuple[str, int]:
    _, secret = _app(settings)
    data = _request(
        "GET",
        f"{GRAPH_ROOT}/access_token",
        "Langzeit-Token",
        params={"grant_type": "ig_exchange_token", "client_secret": secret, "access_token": short},
    )
    token = str(data.get("access_token") or "")
    if not token:
        raise PlatformError("Instagram hat keinen Langzeit-Schlüssel geliefert")
    return token, int(data.get("expires_in") or 0)


def connect(
    session: Session, settings: Settings, channel: Channel, code: str, user_id: int
) -> ChannelCredential:
    """Code → long-lived token → account id; the token is stored encrypted."""
    short, scopes = _short_token(settings, code)
    token, expires_in = _long_token(settings, short)
    me = _get("me", {"fields": "user_id,username", "access_token": token}, "Konto")
    account = str(me.get("user_id") or me.get("id") or "")
    if not account:
        raise PlatformError("Instagram hat kein Konto genannt")
    now = datetime.now(UTC)
    cred = session.scalar(
        select(ChannelCredential).where(ChannelCredential.channel_id == channel.id)
    ) or ChannelCredential(channel_id=channel.id, provider=PROVIDER)
    cred.provider = PROVIDER
    cred.access_token_enc = crypto.encrypt(settings, token)
    cred.refresh_token_enc = None  # the long-lived token renews itself
    cred.expires_at = now + timedelta(seconds=expires_in) if expires_in else None
    cred.scopes = scopes or list(SCOPES)
    cred.external_account_id = account
    cred.external_account_name = f"@{me['username']}" if me.get("username") else account
    cred.connected_by_user_id = user_id
    cred.last_refreshed_at = now
    cred.last_error = None
    session.add(cred)
    return cred


def access_token(
    session: Session, settings: Settings, cred: ChannelCredential, now: datetime | None = None
) -> str:
    """The stored token; renewed when it expires within a week (and is at least 24 h old)."""
    if not cred.access_token_enc:
        raise AuthExpiredError("Kein Instagram-Zugangsschlüssel gespeichert")
    token = crypto.decrypt(settings, cred.access_token_enc)
    now = now or datetime.now(UTC)
    if cred.expires_at is not None and cred.expires_at <= now:
        raise AuthExpiredError("Instagram-Zugang abgelaufen; bitte neu verbinden")
    old_enough = cred.last_refreshed_at is None or now - cred.last_refreshed_at >= MIN_TOKEN_AGE
    if cred.expires_at is not None and cred.expires_at - now < REFRESH_BEFORE and old_enough:
        data = _request(
            "GET",
            f"{GRAPH_ROOT}/refresh_access_token",
            "Verlängern",
            params={"grant_type": "ig_refresh_token", "access_token": token},
        )
        token = str(data.get("access_token") or token)
        cred.access_token_enc = crypto.encrypt(settings, token)
        if data.get("expires_in"):
            cred.expires_at = now + timedelta(seconds=int(data["expires_in"]))
        cred.last_refreshed_at = now
    return token


def publish_reel(
    token: str,
    ig_id: str,
    video_url: str,
    caption: str,
    share_to_feed: bool = True,
    polls: int = 10,
    interval: float = 30.0,
    sleep: Any = time.sleep,
) -> ReelResult:
    """Container with ``video_url`` → wait for ``FINISHED`` → ``media_publish``."""
    limit = _get(
        f"{ig_id}/content_publishing_limit",
        {"fields": "quota_usage,config", "access_token": token},
        "Kontingent",
    )
    usage = (limit.get("data") or [{}])[0]
    total = int((usage.get("config") or {}).get("quota_total") or 0)
    if total and int(usage.get("quota_usage") or 0) >= total:
        raise TransientError(f"Instagram: Kontingent von {total} Beiträgen in 24 h erreicht")
    container = _post(
        f"{ig_id}/media",
        {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption[:2200],
            "share_to_feed": "true" if share_to_feed else "false",
            "access_token": token,
        },
        "Container",
    )
    cid = str(container.get("id") or "")
    if not cid:
        raise PlatformError("Container ohne id beantwortet")
    for i in range(max(1, polls)):
        if i:
            sleep(interval)
        status = str(
            _get(cid, {"fields": "status_code", "access_token": token}, "Status").get("status_code")
            or ""
        )
        if status in ("ERROR", "EXPIRED"):
            raise PlatformError(f"Instagram hat das Video nicht verarbeitet ({status})")
        if status in ("FINISHED", "PUBLISHED"):
            break
    else:
        raise TransientError("Instagram verarbeitet das Video noch; später erneut")
    media = _post(
        f"{ig_id}/media_publish", {"creation_id": cid, "access_token": token}, "Veröffentlichen"
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
