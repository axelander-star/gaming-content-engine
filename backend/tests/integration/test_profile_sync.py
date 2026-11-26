"""Prepared profile (description, keywords, banner) goes to the connected YouTube channel.

Google is never contacted: every HTTP call goes to an ``httpx.MockTransport``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from redis import Redis
from sqlalchemy.orm import Session

from core import crypto
from core.config import Settings
from core.enums import ChannelAuthStatus, ChannelSetupStatus, Language
from models import Channel, ChannelCredential
from models.channel_setup import ChannelSetupTask
from services import branding, profile_sync, youtube
from services.projects import ensure_default_project
from services.seed import seed_base_data
from tests.integration.test_publishing import FakeGoogle, google, settings  # noqa: F401

pytestmark = pytest.mark.integration

CHANNEL_URL = f"{youtube.API}/channels"


def connected(db: Session, settings: Settings) -> Channel:  # noqa: F811
    seed_base_data(db, demo_channels=True)
    project = ensure_default_project(db)
    project.subtopics = ["Rezepte", "Meal Prep"]
    channel = next(
        c for c in db.query(Channel).all() if c.platform.code == "youtube" and c.language == "de"
    )
    task = ChannelSetupTask(
        content_project_id=project.id,
        platform="youtube",
        language=Language.DE,
        status=ChannelSetupStatus.DONE,
        display_name="Kochwerk",
        handle="kochwerk",
        bio="Schnelle Rezepte für jeden Tag.",
        text_source="template",
        banner_uri=branding.store_png(settings, branding.banner_png("Kochwerk", "Rezepte", "x")),
        channel_id=channel.id,
    )
    db.add(task)
    db.flush()
    channel.strategy = {"handle": "kochwerk", "setup_task_id": task.id}
    channel.auth_status = ChannelAuthStatus.AUTHORIZED
    channel.external_channel_id = "UCkoch"
    db.add(
        ChannelCredential(
            channel_id=channel.id,
            provider="youtube",
            access_token_enc=crypto.encrypt(settings, "ya29.access"),
            refresh_token_enc=crypto.encrypt(settings, "1//refresh"),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            scopes=list(youtube.SCOPES),
        )
    )
    db.flush()
    return channel


def test_profile_is_written_with_banner_and_existing_settings_kept(
    db: Session,
    settings: Settings,
    google: FakeGoogle,
    redis_client: Redis,  # noqa: F811
) -> None:
    channel = connected(db, settings)
    current = {
        "items": [
            {
                "brandingSettings": {
                    "channel": {"title": "Kochwerk", "country": "DE", "description": "alt"}
                }
            }
        ]
    }
    google.on("GET", CHANNEL_URL, httpx.Response(200, json=current))
    google.on(
        "POST", profile_sync.BANNER_UPLOAD_URL, httpx.Response(200, json={"url": "https://b/1"})
    )
    google.on("PUT", CHANNEL_URL, httpx.Response(200, json={"id": "UCkoch"}))

    result = profile_sync.sync_youtube(db, settings, redis_client, channel)

    assert result.ok, result.error
    assert result.applied == ["Banner", "Beschreibung", "Stichwörter"]
    assert result.manual == ["Profilbild", "Links"]
    upload = google.sent("POST", profile_sync.BANNER_UPLOAD_URL)[0]
    assert upload.headers["Content-Type"] == "image/png"
    assert upload.headers["Authorization"] == "Bearer ya29.access"
    body = json.loads(google.sent("PUT", CHANNEL_URL)[0].content)
    chan = body["brandingSettings"]["channel"]
    assert body["id"] == "UCkoch"
    assert chan["description"] == "Schnelle Rezepte für jeden Tag."
    assert chan["country"] == "DE"  # untouched fields are sent back, not blanked
    assert "title" not in chan  # never changed
    assert chan["keywords"] == 'Gaming Rezepte "Meal Prep" kochwerk'
    assert body["brandingSettings"]["image"]["bannerExternalUrl"] == "https://b/1"
    assert channel.strategy["profile_sync"]["ok"] is True


def test_failure_is_recorded_and_nothing_counts_as_applied(
    db: Session,
    settings: Settings,
    google: FakeGoogle,
    redis_client: Redis,  # noqa: F811
) -> None:
    channel = connected(db, settings)
    google.on("GET", CHANNEL_URL, httpx.Response(200, json={"items": [{}]}))
    google.on("POST", profile_sync.BANNER_UPLOAD_URL, httpx.Response(200, json={"url": "u"}))
    google.on("PUT", CHANNEL_URL, httpx.Response(403, json={"error": {}}))
    result = profile_sync.sync_youtube(db, settings, redis_client, channel)
    assert not result.ok and result.applied == []
    assert "abgelehnt" in (result.error or "")
    assert channel.strategy["profile_sync"]["ok"] is False


def test_unconnected_channel_is_not_touched(
    db: Session,
    settings: Settings,
    google: FakeGoogle,
    redis_client: Redis,  # noqa: F811
) -> None:
    channel = connected(db, settings)
    channel.auth_status = ChannelAuthStatus.NOT_CONNECTED
    result = profile_sync.sync_youtube(db, settings, redis_client, channel)
    assert not result.ok and result.error == "Kanal ist nicht verbunden"
    assert google.requests == []


def test_keywords_are_capped_and_quoted() -> None:
    from models.projects import ContentProject

    project = ContentProject(
        name="Ernährung", subtopics=["a b"] + [f"w{i}" * 20 for i in range(40)]
    )
    words = profile_sync.keywords(Channel(strategy={}), project)
    assert words.startswith('Ernährung "a b"')
    assert len(words) <= profile_sync.KEYWORDS_MAX
