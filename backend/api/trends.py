"""Trends, trend reports and game profiles (Phase 5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from redis import Redis
from sqlalchemy import select

from api.deps import Admin, AppSettings, DbSession, Viewer, csrf_protect
from core.catalog import audience_for
from core.enums import Language
from models.trends import Game, Trend, TrendReport
from services import audit, source_status
from services.queue import get_redis
from services.trends import latest_trends

router = APIRouter(tags=["trends"])


class TrendOut(BaseModel):
    game_id: int
    game: str
    language: Language | None
    score: float
    growth_pct: float | None
    components: dict[str, float]
    unknown: list[str]
    audience: str | None
    audience_label: str
    sources: list[str]
    is_new: bool
    is_mock: bool
    detected_at: datetime
    top_idea: str | None


class TrendReportOut(BaseModel):
    id: int
    language: Language
    created_at: datetime
    sources: list[str]
    is_mock: bool
    summary: str
    items: list[dict[str, Any]]
    by_audience: dict[str, Any]


class GameOut(BaseModel):
    id: int
    name: str
    slug: str
    categories: list[str]
    publisher: str | None
    steam_app_id: int | None
    twitch_game_id: str | None
    is_test_data: bool
    profiled_at: datetime | None
    profile: dict[str, Any]


def _growth(trend: Trend) -> float | None:
    rates = [
        s["growth_pct"]
        for s in (trend.metrics or {}).get("per_source", {}).values()
        if isinstance(s, dict) and s.get("growth_pct") is not None
    ]
    return round(sum(rates) / len(rates), 1) if rates else None


def _trend_out(trend: Trend, game: Game) -> TrendOut:
    _, label_de, label_en = audience_for(game.categories or [])
    metrics = trend.metrics or {}
    ideas = (game.profile or {}).get("video_ideas") or []
    title_key = "title_de" if trend.language == Language.DE else "title_en"
    return TrendOut(
        game_id=game.id,
        game=game.name,
        language=trend.language,
        score=float(trend.score),
        growth_pct=_growth(trend),
        components=metrics.get("components", {}),
        unknown=metrics.get("unknown", []),
        audience=trend.audience,
        audience_label=label_de if trend.language == Language.DE else label_en,
        sources=sorted(metrics.get("per_source", {})),
        is_new=bool(metrics.get("is_new")),
        is_mock=trend.is_mock,
        detected_at=trend.detected_at,
        top_idea=ideas[0].get(title_key) if ideas else None,
    )


@router.get("/trends", response_model=list[TrendOut])
def list_trends(
    _: Viewer,
    db: DbSession,
    language: Language = Language.DE,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> list[TrendOut]:
    rows = latest_trends(db, language, limit)
    games = {
        g.id: g for g in db.scalars(select(Game).where(Game.id.in_([r.game_id for r in rows])))
    }
    return [_trend_out(r, games[r.game_id]) for r in rows]


@router.get("/trends/report", response_model=TrendReportOut | None)
def latest_report(_: Viewer, db: DbSession, language: Language = Language.DE) -> TrendReport | None:
    return db.scalar(
        select(TrendReport)
        .where(TrendReport.language == language)
        .order_by(TrendReport.id.desc())
        .limit(1)
    )


@router.get("/games", response_model=list[GameOut])
def list_games(
    _: Viewer, db: DbSession, limit: Annotated[int, Query(ge=1, le=500)] = 100
) -> list[Game]:
    return list(db.scalars(select(Game).order_by(Game.name).limit(limit)))


@router.get("/games/{game_id}", response_model=GameOut)
def get_game(game_id: int, _: Viewer, db: DbSession) -> Game:
    game = db.get(Game, game_id)
    if game is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Game not found")
    return game


class HistoryPoint(BaseModel):
    detected_at: datetime
    score: float
    is_mock: bool
    metrics: dict[str, float]  # metric -> value, e.g. video_views, live_viewers, players
    growth_pct: dict[str, float]


@router.get("/games/{game_id}/history", response_model=list[HistoryPoint])
def game_history(
    game_id: int,
    _: Viewer,
    db: DbSession,
    language: Language = Language.DE,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> list[HistoryPoint]:
    """Score and raw values of one game over time (one point per trend run)."""
    if db.get(Game, game_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Game not found")
    since = datetime.now(UTC) - timedelta(days=days)
    rows = db.scalars(
        select(Trend)
        .where(Trend.game_id == game_id, Trend.language == language, Trend.detected_at >= since)
        .order_by(Trend.detected_at)
    )
    points = []
    for t in rows:
        per_source = (t.metrics or {}).get("per_source", {})
        values = {
            str(v["metric"]): float(v["value"])
            for v in per_source.values()
            if isinstance(v, dict) and v.get("value") is not None
        }
        growth = {
            str(v["metric"]): float(v["growth_pct"])
            for v in per_source.values()
            if isinstance(v, dict) and v.get("growth_pct") is not None
        }
        points.append(
            HistoryPoint(
                detected_at=t.detected_at,
                score=float(t.score),
                is_mock=t.is_mock,
                metrics=values,
                growth_pct=growth,
            )
        )
    return points


# --- connection status of the trend sources -------------------------------------

RedisDep = Annotated[Redis, Depends(get_redis)]
SourceName = Literal["youtube", "twitch", "steam"]


class SourceStatusOut(BaseModel):
    name: str
    label: str
    mode: str
    configured: bool
    credentials: list[str]  # variable names only, never values
    quota_used: int
    quota_limit: int
    quota_unit: str
    last: dict[str, Any] | None


@router.get("/trends/sources", response_model=list[SourceStatusOut])
def source_overview(_: Viewer, settings: AppSettings, redis: RedisDep) -> list[dict[str, Any]]:
    return source_status.overview(settings, redis)


@router.post(
    "/trends/sources/{name}/test",
    response_model=SourceStatusOut,
    dependencies=[Depends(csrf_protect)],
)
def test_source(
    name: SourceName, admin: Admin, db: DbSession, settings: AppSettings, redis: RedisDep
) -> dict[str, Any]:
    """One read-only request against the real API, counted against the daily quota.

    Runs only when an admin presses the button; works in mock mode too, so the
    keys can be checked before live mode is switched on."""
    from services.sources.live import SteamSource, TwitchSource, YouTubeSource

    result = (
        YouTubeSource(settings, redis).check()
        if name == "youtube"
        else TwitchSource(settings, redis).check()
        if name == "twitch"
        else SteamSource(settings, redis).check()
    )
    entry = source_status.record(redis, result, settings.trend_sources_mode, kind="test")
    audit.record(
        db,
        "trend_source.test",
        user_id=admin.id,
        entity_type="trend_sources",
        after={"source": name, "state": entry["state"], "errors": entry["errors"]},
    )
    db.commit()
    return next(s for s in source_status.overview(settings, redis) if s["name"] == name)
