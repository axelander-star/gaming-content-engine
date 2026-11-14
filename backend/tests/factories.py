"""Minimal helpers to build a complete, traceable object chain for tests."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.enums import AssetKind, Language, LicenseStatus, SourceType
from models import (
    Asset,
    Channel,
    Clip,
    Creator,
    Game,
    GameplayFile,
    License,
    Scene,
    Source,
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


def build_chain(db: Session, language: Language = Language.DE) -> Chain:
    seed_base_data(db)
    channel = db.scalars(select(Channel).where(Channel.language == language)).first()
    assert channel is not None
    suffix = uuid4().hex[:8]
    game = Game(name="Test Game", slug=f"test-game-{suffix}")
    creator = Creator(name="Test Creator")
    db.add_all([game, creator])
    db.flush()
    source = Source(creator_id=creator.id, type=SourceType.LICENSED_CREATOR, name="Upload")
    db.add(source)
    db.flush()
    lic = License(source_id=source.id, status=LicenseStatus.APPROVED, allows_commercial_use=True)
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
