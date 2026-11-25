"""Schema, constraints and traceability against a real PostgreSQL."""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from core.enums import Language, LicenseStatus, PublishingJobStatus
from models import Channel, License, Platform, Post, PublishingJob
from services.seed import seed_base_data
from tests.factories import build_chain

pytestmark = pytest.mark.integration

SPEC_TABLES = {
    "users",
    "channels",
    "platforms",
    "games",
    "trends",
    "creators",
    "sources",
    "licenses",
    "assets",
    "gameplay_files",
    "scenes",
    "clips",
    "variants",
    "scripts",
    "voiceovers",
    "subtitles",
    "quality_checks",
    "publishing_jobs",
    "posts",
    "metrics",
    "analytics_snapshots",
    "agent_runs",
    "agent_decisions",
    "costs",
    "system_settings",
    "notifications",
    "audit_logs",
}


def test_all_spec_tables_exist(engine: Engine) -> None:
    tables = set(inspect(engine).get_table_names())
    assert tables >= SPEC_TABLES, SPEC_TABLES - tables


def test_seed_creates_eight_blocked_channels_idempotently(db: Session) -> None:
    first = seed_base_data(db, demo_channels=True)
    second = seed_base_data(db, demo_channels=True)
    assert first == {"platforms": 4, "channels": 8, "policies": 1}
    assert second == {"platforms": 0, "channels": 0, "policies": 0}
    channels = db.scalars(select(Channel)).all()
    assert len(channels) == 8
    assert {c.language for c in channels} == {Language.DE, Language.EN}
    assert all(c.is_paused and c.max_posts_per_day == 0 for c in channels)
    assert len(db.scalars(select(Platform)).all()) == 4


def test_channel_max_must_not_be_below_min(db: Session) -> None:
    seed_base_data(db, demo_channels=True)
    channel = db.scalars(select(Channel)).first()
    assert channel is not None
    channel.min_posts_per_day = 3
    channel.max_posts_per_day = 1
    with pytest.raises(IntegrityError):
        db.flush()


def test_invalid_enum_value_rejected_by_database(db: Session) -> None:
    seed_base_data(db, demo_channels=True)
    with pytest.raises(IntegrityError):
        db.execute(text("UPDATE channels SET auth_status = 'hacked'"))


def test_invalid_enum_value_rejected_by_orm(db: Session) -> None:
    seed_base_data(db, demo_channels=True)
    channel = db.scalars(select(Channel)).first()
    assert channel is not None
    channel.auth_status = "hacked"  # type: ignore[assignment]
    with pytest.raises(StatementError):
        db.flush()


def test_asset_requires_license(db: Session) -> None:
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO assets (source_id, license_id, kind, storage_uri) "
                "VALUES (NULL, NULL, 'video', 'x')"
            )
        )


def _publish(db: Session, chain_variant_id: int, channel_id: int, key: str) -> Post:
    job = PublishingJob(
        variant_id=chain_variant_id,
        channel_id=channel_id,
        idempotency_key=key,
        status=PublishingJobStatus.SUCCEEDED,
    )
    db.add(job)
    db.flush()
    post = Post(publishing_job_id=job.id, variant_id=chain_variant_id, channel_id=channel_id)
    db.add(post)
    db.flush()
    return post


def test_duplicate_post_for_same_variant_and_channel_rejected(db: Session) -> None:
    chain = build_chain(db)
    _publish(db, chain.variant.id, chain.channel.id, "k1")
    with pytest.raises(IntegrityError):
        _publish(db, chain.variant.id, chain.channel.id, "k2")


def test_duplicate_idempotency_key_rejected(db: Session) -> None:
    chain = build_chain(db)
    db.add(
        PublishingJob(
            variant_id=chain.variant.id, channel_id=chain.channel.id, idempotency_key="same"
        )
    )
    db.flush()
    db.add(
        PublishingJob(
            variant_id=chain.variant.id, channel_id=chain.channel.id, idempotency_key="same"
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_post_traceable_to_license(db: Session) -> None:
    """PROJECT_SPEC section 10: every video must be traceable to its source."""
    chain = build_chain(db)
    post = _publish(db, chain.variant.id, chain.channel.id, "trace")
    row = db.execute(
        text(
            """
            SELECT l.id AS license_id, s.id AS source_id
            FROM posts p
            JOIN publishing_jobs j ON j.id = p.publishing_job_id
            JOIN variants v ON v.id = j.variant_id
            JOIN clips c ON c.id = v.clip_id
            JOIN scenes sc ON sc.id = c.scene_id
            JOIN gameplay_files g ON g.id = sc.gameplay_file_id
            JOIN assets a ON a.id = g.asset_id
            JOIN sources s ON s.id = a.source_id
            JOIN licenses l ON l.id = a.license_id
            WHERE p.id = :pid
            """
        ),
        {"pid": post.id},
    ).one()
    assert row.license_id == chain.license.id


def test_license_permissions_default_to_deny(db: Session) -> None:
    chain = build_chain(db)
    lic = License(source_id=chain.license.source_id)  # no terms given -> everything denied
    db.add(lic)
    db.flush()
    db.refresh(lic)
    assert lic.status == LicenseStatus.PENDING
    assert lic.allows_commercial_use is False
    assert lic.publisher_permission is False
    assert lic.allows_editing is False
    assert lic.allows_short_form is False
    assert lic.allows_monetization is False
    assert lic.music_cleared is False
    assert lic.allowed_platforms == []
