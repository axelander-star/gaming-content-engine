"""Minimal helpers to build a complete, traceable object chain for tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.enums import (
    AssetKind,
    Language,
    LicenseStatus,
    PlatformCode,
    PolicyStatus,
    SourceType,
    UserRole,
)
from models import (
    Asset,
    Channel,
    Clip,
    Creator,
    Game,
    GameplayFile,
    License,
    PublisherPolicy,
    Scene,
    Source,
    User,
    Variant,
)
from services.seed import seed_base_data


@dataclass
class Chain:
    channel: Channel
    license: License
    gameplay_file: GameplayFile
    scene: Scene
    clip: Clip
    variant: Variant


def full_license(**overrides: Any) -> dict[str, Any]:
    """License terms that pass every rights criterion (tests switch single ones off)."""
    terms: dict[str, Any] = {
        "status": LicenseStatus.APPROVED,
        "allows_commercial_use": True,
        "allows_editing": True,
        "allows_short_form": True,
        "allows_monetization": True,
        "music_cleared": True,
        "allowed_platforms": [p.value for p in PlatformCode],
        "allowed_languages": [lang.value for lang in Language],
        "document_uri": "local://licenses/test.pdf",
        "verified_at": datetime.now(UTC),
    }
    terms.update(overrides)
    return terms


def build_chain(db: Session, language: Language = Language.DE) -> Chain:
    seed_base_data(db, demo_channels=True)
    # ordered: without it Postgres may hand out any channel (e.g. Facebook as the origin)
    channel = db.scalars(
        select(Channel).where(Channel.language == language).order_by(Channel.id)
    ).first()
    assert channel is not None
    suffix = uuid4().hex[:8]
    game = Game(name=f"Test Game {suffix}", slug=f"test-game-{suffix}", categories=["shooter"])
    creator = Creator(name="Test Creator")
    verifier = User(email=f"verifier-{suffix}@example.com", password_hash="x", role=UserRole.ADMIN)
    db.add_all([game, creator, verifier])
    db.flush()
    db.add(PublisherPolicy(game_id=game.id, status=PolicyStatus.PERMITTED, notes="test"))
    source = Source(
        creator_id=creator.id,
        type=SourceType.LICENSED_CREATOR,
        name="Upload",
        provenance_notes="Creator agreement (test)",
    )
    db.add(source)
    db.flush()
    lic = License(source_id=source.id, verified_by_user_id=verifier.id, **full_license())
    db.add(lic)
    db.flush()
    asset = Asset(
        source_id=source.id,
        license_id=lic.id,
        game_id=game.id,
        kind=AssetKind.VIDEO,
        storage_uri="mock://raw.mp4",
    )
    db.add(asset)
    db.flush()
    gf = GameplayFile(
        asset_id=asset.id, game_id=game.id, storage_uri="mock://raw.mp4", sha256=uuid4().hex * 2
    )
    db.add(gf)
    db.flush()
    scene = Scene(gameplay_file_id=gf.id, start_s=1.0, end_s=12.5)
    db.add(scene)
    db.flush()
    clip = Clip(scene_id=scene.id, start_s=1.0, end_s=12.5)
    db.add(clip)
    db.flush()
    variant = Variant(clip_id=clip.id, channel_id=channel.id, language=language, variant_label="A")
    db.add(variant)
    db.flush()
    return Chain(channel, lic, gf, scene, clip, variant)
