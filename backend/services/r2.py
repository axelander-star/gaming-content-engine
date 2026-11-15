"""Cloudflare R2 (S3-compatible) for short-lived public video addresses (extension E8).

The Instagram API with Instagram Login only accepts a ``video_url`` that Meta
fetches from a public server; the resumable upload is reserved for apps with
Facebook Login. The dashboard and the API stay private (Cloudflare Access), so the
video is copied to a private R2 bucket and Meta gets a *presigned* GET address
that expires after ``R2_PRESIGN_SECONDS``. After publishing the object is deleted.

Requests are signed with AWS Signature Version 4 (region ``auto``, service ``s3``)
as documented for R2's S3 API; no SDK is needed. Tests replace
:data:`services.platform.TRANSPORT`, nothing reaches Cloudflare.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from core.config import Settings
from services import platform

REGION = "auto"
SERVICE = "s3"
UNSIGNED = "UNSIGNED-PAYLOAD"


def configured(settings: Settings) -> bool:
    return bool(
        settings.r2_account_id
        and settings.r2_bucket
        and settings.r2_access_key_id.get_secret_value()
        and settings.r2_secret_access_key.get_secret_value()
    )


def _require(settings: Settings) -> None:
    if not configured(settings):
        raise platform.NotConfiguredError(
            "Cloudflare R2 ist nicht eingerichtet (R2_ACCOUNT_ID, R2_BUCKET, Zugangsschlüssel)"
        )


def _host(settings: Settings) -> str:
    return f"{settings.r2_account_id}.r2.cloudflarestorage.com"


def _path(settings: Settings, key: str) -> str:
    return "/" + quote(settings.r2_bucket, safe="") + "/" + quote(key, safe="/-_.~")


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def _signing_key(secret: str, day: str, region: str = REGION) -> bytes:
    k = _sign(("AWS4" + secret).encode(), day)
    k = _sign(k, region)
    k = _sign(k, SERVICE)
    return _sign(k, "aws4_request")


def _canonical_query(params: dict[str, str]) -> str:
    return "&".join(
        f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in sorted(params.items())
    )


def presign(
    settings: Settings,
    method: str,
    key: str,
    seconds: int,
    now: datetime | None = None,
) -> str:
    """A presigned URL (query-string authentication) for ``method`` on ``key``."""
    _require(settings)
    return presign_url(
        method,
        _host(settings),
        _path(settings, key),
        access_key=settings.r2_access_key_id.get_secret_value(),
        secret_key=settings.r2_secret_access_key.get_secret_value(),
        seconds=seconds,
        now=now or datetime.now(UTC),
    )


def presign_url(
    method: str,
    host: str,
    path: str,
    *,
    access_key: str,
    secret_key: str,
    seconds: int,
    now: datetime,
    region: str = REGION,
) -> str:
    """AWS Signature Version 4, query-string variant (``path`` already URI-encoded)."""
    stamp, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    scope = f"{day}/{region}/{SERVICE}/aws4_request"
    params = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": f"{access_key}/{scope}",
        "X-Amz-Date": stamp,
        "X-Amz-Expires": str(max(1, min(seconds, 7 * 24 * 3600))),
        "X-Amz-SignedHeaders": "host",
    }
    query = _canonical_query(params)
    canonical = "\n".join([method, path, query, f"host:{host}\n", "host", UNSIGNED])
    to_sign = "\n".join(
        ["AWS4-HMAC-SHA256", stamp, scope, hashlib.sha256(canonical.encode()).hexdigest()]
    )
    signature = hmac.new(
        _signing_key(secret_key, day, region), to_sign.encode(), hashlib.sha256
    ).hexdigest()
    return f"https://{host}{path}?{query}&X-Amz-Signature={signature}"


def put_file(settings: Settings, key: str, path: Path, content_type: str = "video/mp4") -> None:
    """Upload ``path`` to the bucket (presigned PUT, one request)."""
    url = presign(settings, "PUT", key, 900)
    with platform.http_client(600) as client, path.open("rb") as fh:
        try:
            res = client.put(url, content=fh.read(), headers={"Content-Type": content_type})
        except Exception as exc:  # network problems: try again later
            # no exception text: it may contain the signed address
            raise platform.TransientError("R2-Upload: Verbindung fehlgeschlagen") from exc
    if res.status_code >= 500:
        raise platform.TransientError(f"R2-Upload: {res.status_code}", res.status_code)
    if res.status_code >= 400:
        raise platform.PlatformError(f"R2-Upload abgelehnt: {res.status_code}", res.status_code)


def delete(settings: Settings, key: str) -> bool:
    """Best effort removal after publishing."""
    try:
        with platform.http_client(30) as client:
            res = client.delete(presign(settings, "DELETE", key, 300))
    except Exception:
        return False
    return res.status_code in (200, 204, 404)


def public_video_url(settings: Settings, key: str, path: Path) -> str:
    """Upload and return a GET address that expires after ``R2_PRESIGN_SECONDS``."""
    put_file(settings, key, path)
    return presign(settings, "GET", key, settings.r2_presign_seconds)
