"""Video production: analysed scenes, rendered clips and render capacity (Phase 7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select

from api.deps import AppSettings, DbSession, Viewer
from core.enums import VideoStatus
from models.production import Clip, GameplayFile, Scene, Script, Variant
from models.rights import Asset
from models.trends import Game
from services import storage
from services.controls import get_operations

router = APIRouter(tags=["production"])


class SceneOut(BaseModel):
    id: int
    rank: int | None
    start_s: float
    end_s: float
    score: float | None
    scores: dict[str, Any]
    tags: list[Any]
    selected: bool


class ScriptOut(BaseModel):
    id: int
    version: int
    source: str
    hook: str | None
    voiceover_text: str | None
    call_to_action: str | None
    title: str | None
    description: str | None
    beats: list[Any]


class VariantBrief(BaseModel):
    id: int
    language: str
    label: str
    status: VideoStatus
    channel_id: int
    error_message: str | None
    video_format: str | None
    hook_type: str | None
    concept: dict[str, Any]
    script: ScriptOut | None


class ClipOut(BaseModel):
    id: int
    material_id: int
    material_title: str | None
    game: str | None
    scene: SceneOut
    start_s: float
    end_s: float
    rendered: bool
    width: int | None
    height: int | None
    fps: float | None
    duration_s: float | None
    size_bytes: int | None
    video_codec: str | None
    audio_codec: str | None
    layout: str | None
    render_seconds: float | None
    realtime_factor: float | None
    rendered_at: datetime | None
    variants: list[VariantBrief]


def _scene_out(sc: Scene) -> SceneOut:
    return SceneOut(
        id=sc.id,
        rank=sc.rank,
        start_s=sc.start_s,
        end_s=sc.end_s,
        score=sc.score,
        scores=sc.scores or {},
        tags=sc.tags or [],
        selected=sc.selected,
    )


@router.get("/production/clips", response_model=list[ClipOut])
def list_clips(
    _: Viewer, db: DbSession, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[ClipOut]:
    rows = db.execute(
        select(Clip, Scene, GameplayFile)
        .join(Scene, Scene.id == Clip.scene_id)
        .join(GameplayFile, GameplayFile.id == Scene.gameplay_file_id)
        .order_by(Clip.id.desc())
        .limit(limit)
    ).all()
    clip_ids = [c.id for c, _, _ in rows]
    variants: dict[int, list[VariantBrief]] = {}
    rows_v = list(
        db.scalars(select(Variant).where(Variant.clip_id.in_(clip_ids)).order_by(Variant.id))
    )
    scripts: dict[int, Script] = {}
    for sc in db.scalars(
        select(Script).where(Script.variant_id.in_([v.id for v in rows_v])).order_by(Script.version)
    ):
        scripts[sc.variant_id] = sc  # latest version wins
    for v in rows_v:
        latest = scripts.get(v.id)
        variants.setdefault(v.clip_id, []).append(
            VariantBrief(
                id=v.id,
                language=v.language.value,
                label=v.variant_label,
                status=v.status,
                channel_id=v.channel_id,
                error_message=v.error_message,
                video_format=v.video_format,
                hook_type=v.hook_type,
                concept=v.concept or {},
                script=ScriptOut(
                    id=latest.id,
                    version=latest.version,
                    source=latest.source,
                    hook=latest.hook,
                    voiceover_text=latest.voiceover_text,
                    call_to_action=latest.call_to_action,
                    title=latest.title,
                    description=latest.description,
                    beats=latest.beats or [],
                )
                if latest
                else None,
            )
        )
    games = {g.id: g.name for g in db.scalars(select(Game))} if rows else {}
    asset_ids = {m.asset_id for _, _, m in rows}
    titles = {a.id: a.title for a in db.scalars(select(Asset).where(Asset.id.in_(asset_ids)))}
    out = []
    for clip, scene, material in rows:
        out.append(
            ClipOut(
                id=clip.id,
                material_id=material.id,
                material_title=titles.get(material.asset_id),
                game=games.get(material.game_id) if material.game_id else None,
                scene=_scene_out(scene),
                start_s=clip.start_s,
                end_s=clip.end_s,
                rendered=clip.storage_uri is not None,
                width=clip.width,
                height=clip.height,
                fps=clip.fps,
                duration_s=clip.duration_s,
                size_bytes=clip.size_bytes,
                video_codec=clip.video_codec,
                audio_codec=clip.audio_codec,
                layout=clip.layout,
                render_seconds=clip.render_seconds,
                realtime_factor=(clip.render_params or {}).get("realtime_factor"),
                rendered_at=clip.rendered_at,
                variants=variants.get(clip.id, []),
            )
        )
    return out


@router.get("/materials/{material_id}/scenes", response_model=list[SceneOut])
def material_scenes(material_id: int, _: Viewer, db: DbSession) -> list[SceneOut]:
    if db.get(GameplayFile, material_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Material not found")
    scenes = db.scalars(
        select(Scene).where(Scene.gameplay_file_id == material_id).order_by(Scene.rank, Scene.id)
    )
    return [_scene_out(s) for s in scenes]


@router.get("/clips/{clip_id}/file")
def clip_file(clip_id: int, _: Viewer, db: DbSession, settings: AppSettings) -> FileResponse:
    clip = db.get(Clip, clip_id)
    if clip is None or clip.storage_uri is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Clip not rendered")
    try:
        path = storage.resolve(settings, clip.storage_uri)
    except storage.StorageError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Clip file not found") from exc
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Clip file not found")
    return FileResponse(path, media_type="video/mp4", filename=f"clip-{clip.id}.mp4")


class CapacityOut(BaseModel):
    clips_rendered_7d: int
    render_seconds_7d: float
    clip_seconds_7d: float
    realtime_factor: float | None  # clip seconds per render second (>1 faster than real time)
    clips_per_hour_per_slot: float | None
    parallel_slots: int
    clips_per_hour: float | None
    waiting_for_render: int


@router.get("/production/capacity", response_model=CapacityOut)
def capacity(_: Viewer, db: DbSession) -> CapacityOut:
    """Measured render capacity of this machine (last 7 days), for planning (Phase 11)."""
    since = datetime.now(UTC) - timedelta(days=7)
    count, render_sum, clip_sum = db.execute(
        select(
            func.count(Clip.id),
            func.coalesce(func.sum(Clip.render_seconds), 0.0),
            func.coalesce(func.sum(Clip.duration_s), 0.0),
        ).where(Clip.rendered_at >= since)
    ).one()
    render_s, clip_s = float(render_sum or 0.0), float(clip_sum or 0.0)
    slots = get_operations(db).max_parallel_render_jobs
    factor = round(clip_s / render_s, 2) if render_s else None
    per_slot = round(3600 / (render_s / count), 1) if count and render_s else None
    waiting = db.scalar(
        select(func.count(Variant.id)).where(Variant.status == VideoStatus.SCENE_SELECTED)
    )
    return CapacityOut(
        clips_rendered_7d=int(count),
        render_seconds_7d=round(render_s, 1),
        clip_seconds_7d=round(clip_s, 1),
        realtime_factor=factor,
        clips_per_hour_per_slot=per_slot,
        parallel_slots=slots,
        clips_per_hour=round(per_slot * slots, 1) if per_slot else None,
        waiting_for_render=int(waiting or 0),
    )
