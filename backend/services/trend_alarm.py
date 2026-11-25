"""Trend alarm (Ausbau A11): spot a topic that takes off, draft videos, ask once.

What is watched (official, free sources only):

* the YouTube trending list (``videos.list?chart=mostPopular``, 1 quota unit per
  call; once in general and once for the gaming category 20 per region), and
* the competitor radar (A5): videos far above a watched channel's usual views.

Nothing of the other video is downloaded or reused (platform terms, copyright):
the alarm reads only public numbers and the title, and the drafts are own
productions (own text, voice and pictures) about the topic.

Each signal gets a transparent score (reach, speed, outlier, freshness, fit,
campaign money). From ``TREND_ALARM_THRESHOLD`` on, an alarm is created, the
own production agent renders ``TREND_ALARM_DRAFTS`` drafts with different
angles, they are prepared as posts for the topic area's channels, and a push
goes to the phone with the facts and a link to the one-tap approval.

Autopilot: only with ``TREND_AUTOPILOT_ENABLED=true`` *and* the channel's own
switch, and only from ``TREND_AUTOPILOT_MIN_SCORE``, the first draft is approved
for that channel without a person. Publishing itself still follows
``PUBLISHING_MODE`` (mock by default) and the publishing strategy (time, amount).
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import (
    CampaignStatus,
    ContentProjectStatus,
    Language,
    NotificationLevel,
    ProductionStatus,
    VideoStatus,
)
from models.campaigns import Campaign
from models.channels import Channel
from models.competitors import Competitor, CompetitorVideo
from models.library import OwnProduction
from models.production import Variant
from models.projects import ContentProject
from models.trend_alarms import TrendAlarm
from services import ai, approval, competitors, notify, own_production, planning
from services.channel_setup import is_placeholder

log = logging.getLogger(__name__)

API = competitors.API
GAMING_CATEGORY = "20"
CHART_SIZE = 50
#: Competitor videos older than this are no news any more.
FRESH_HOURS = 72
#: A ready alarm waits this long for a decision, then it expires.
EXPIRE_HOURS = 48
#: Drafts that are not rendered after this long are finished with what is there.
DRAFT_TIMEOUT = timedelta(hours=2)
WEIGHTS = {
    "reach": 0.25,
    "speed": 0.25,
    "outlier": 0.15,
    "fresh": 0.15,
    "fit": 0.10,
    "money": 0.10,
}
#: (label, instruction) – one draft per angle, in this order.
ANGLES: tuple[tuple[str, str], ...] = (
    (
        "Kurz erklärt",
        "Erkläre in 30 bis 45 Sekunden, worum es geht und warum gerade alle darüber reden.",
    ),
    (
        "Meinung",
        "Eine klare eigene Einschätzung: Was steckt dahinter, lohnt es sich, was übersehen viele?",
    ),
    (
        "Drei Fakten",
        "Drei überraschende Fakten oder Tipps zum Thema, knapp und mit Neugier am Anfang.",
    ),
    ("Für Einsteiger", "Der schnelle Überblick für alle, die erst jetzt davon hören."),
    ("Was kommt als Nächstes", "Wie es weitergehen könnte, ohne Zahlen zu erfinden."),
)
OPEN = ("drafting", "ready")

#: Tests swap in an ``httpx.MockTransport``.
TRANSPORT: httpx.BaseTransport | None = None


class TrendAlarmError(ValueError):
    """An action on an alarm that is not possible (German message)."""

    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


# --- signals -------------------------------------------------------------------------


@dataclass
class Signal:
    key: str
    project_id: int
    source: str
    title: str
    url: str | None
    creator: str | None
    published_at: datetime | None
    views: int
    likes: int | None = None
    comments: int | None = None
    outlier: float | None = None
    chart_rank: int | None = None
    region: str | None = None
    keyword: str | None = None
    is_mock: bool = False


def _fold(text: str) -> str:
    return planning._norm(text)


def keywords(project: ContentProject) -> list[str]:
    words = [project.name, *[str(s) for s in project.subtopics or []]]
    return [w for w in dict.fromkeys(" ".join(w.split()) for w in words) if len(w) >= 3]


def is_gaming(project: ContentProject) -> bool:
    text = _fold(f"{project.slug} {project.name}")
    return any(k in text for k in ("gaming", "games", "spiele", "gamer", "zocken"))


def _match(project: ContentProject, text: str) -> str | None:
    folded = _fold(text)
    for word in keywords(project):
        pattern = r"(?<![a-z0-9])" + re.escape(_fold(word)) + r"(?![a-z0-9])"
        if re.search(pattern, folded):
            return word
    return None


def _chart_live(
    settings: Settings, http: httpx.Client, region: str, category: str | None
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "part": "snippet,statistics",
        "chart": "mostPopular",
        "regionCode": region,
        "maxResults": CHART_SIZE,
    }
    if category:
        params["videoCategoryId"] = category
    data = competitors._get(http, settings, "videos", **params)
    return [v for v in data.get("items") or [] if isinstance(v, dict)]


def _chart_signals(
    projects: list[ContentProject], raw: list[dict[str, Any]], region: str, gaming: bool
) -> list[Signal]:
    out: list[Signal] = []
    for rank, video in enumerate(raw, start=1):
        vid = str(video.get("id") or "")
        snippet = video.get("snippet") or {}
        stats = video.get("statistics") or {}
        title = " ".join(str(snippet.get("title") or "").split())[:300]
        if not vid or not title:
            continue
        tags = " ".join(str(t) for t in (snippet.get("tags") or [])[:20])
        for project in projects:
            hit = _match(project, f"{title} {tags}")
            if hit is None and not (gaming and is_gaming(project)):
                continue
            out.append(
                Signal(
                    key=f"yt:{vid}:{project.id}",
                    project_id=project.id,
                    source="youtube_chart",
                    title=title,
                    url=f"https://www.youtube.com/watch?v={vid}",
                    creator=str(snippet.get("channelTitle") or "")[:200] or None,
                    published_at=competitors._time(snippet.get("publishedAt")),
                    views=competitors._int(stats.get("viewCount")) or 0,
                    likes=competitors._int(stats.get("likeCount")),
                    comments=competitors._int(stats.get("commentCount")),
                    chart_rank=rank,
                    region=region,
                    keyword=hit,
                )
            )
    return out


def mock_signals(projects: list[ContentProject], now: datetime) -> list[Signal]:
    """Labelled test signals: one clear hit per topic area and day, two weaker ones."""
    out: list[Signal] = []
    day = now.date().isoformat()
    for project in projects:
        topic = keywords(project)[-1] if keywords(project) else project.name
        rows = (
            (2_400_000, 8, f"[Test] {topic}: Das Video, über das gerade alle reden", 2),
            (180_000, 30, f"[Test] {topic} im Alltag", 17),
            (60_000, 50, f"[Test] Neues zu {topic}", 38),
        )
        for i, (views, hours, title, rank) in enumerate(rows):
            out.append(
                Signal(
                    key=f"mock:{day}:{project.id}:{i}",
                    project_id=project.id,
                    source="youtube_chart",
                    title=title,
                    url=None,
                    creator="Testkanal",
                    published_at=now - timedelta(hours=hours),
                    views=views,
                    likes=views // 30,
                    comments=views // 400,
                    chart_rank=rank,
                    region="DE",
                    keyword=topic,
                    is_mock=True,
                )
            )
    return out


def competitor_signals(
    session: Session, projects: list[ContentProject], now: datetime
) -> list[Signal]:
    ids = [p.id for p in projects]
    rows = session.execute(
        select(CompetitorVideo, Competitor)
        .join(Competitor, Competitor.id == CompetitorVideo.competitor_id)
        .where(
            Competitor.active.is_(True),
            Competitor.content_project_id.in_(ids),
            CompetitorVideo.outlier >= competitors.OUTLIER_FACTOR,
            CompetitorVideo.published_at >= now - timedelta(hours=FRESH_HOURS),
        )
    ).all()
    return [
        Signal(
            key=f"comp:{video.id}",
            project_id=comp.content_project_id,
            source="competitor",
            title=video.title,
            url=video.url,
            creator=comp.name or comp.handle,
            published_at=video.published_at,
            views=video.views,
            likes=video.likes,
            comments=video.comments,
            outlier=video.outlier,
            is_mock=video.is_mock,
        )
        for video, comp in rows
    ]


def collect(
    session: Session,
    settings: Settings,
    projects: list[ContentProject],
    now: datetime,
    client: httpx.Client | None = None,
    include_mock: bool = False,
) -> tuple[list[Signal], list[str]]:
    """All signals of all sources; the second value lists source errors (German).

    Without live YouTube data the test signals come only on a manual check, so the
    phone does not get a test alarm every day.
    """
    signals = competitor_signals(session, projects, now)
    errors: list[str] = []
    if not competitors.live(settings):
        if include_mock:
            signals += mock_signals(projects, now)
        return signals, errors
    regions = [r.strip().upper() for r in settings.trend_alarm_regions.split(",") if r.strip()]
    own = client is None
    http = client or httpx.Client(timeout=settings.http_timeout_s, transport=TRANSPORT)
    try:
        for region in regions:
            if not re.fullmatch(r"[A-Z]{2}", region):
                errors.append(f"Region {region} ungültig")
                continue
            categories: list[str | None] = [None]
            if any(is_gaming(p) for p in projects):
                categories.append(GAMING_CATEGORY)
            for category in categories:
                try:
                    raw = _chart_live(settings, http, region, category)
                except (competitors.RadarError, httpx.HTTPError, ValueError) as exc:
                    reason = (
                        str(exc) if isinstance(exc, competitors.RadarError) else type(exc).__name__
                    )
                    errors.append(f"YouTube-Trends {region}: {reason}"[:300])
                    continue
                signals += _chart_signals(projects, raw, region, category == GAMING_CATEGORY)
    finally:
        if own:
            http.close()
    return signals, errors


# --- scoring -------------------------------------------------------------------------


def _clamp(value: float) -> int:
    return max(0, min(100, round(value)))


def campaign_cpm(session: Session, project_id: int) -> tuple[str, float] | None:
    """Best active campaign of the topic area (name, CPM in USD), if any."""
    row = session.execute(
        select(Campaign.name, Campaign.cpm_usd)
        .where(
            Campaign.content_project_id == project_id,
            Campaign.status == CampaignStatus.ACTIVE,
            Campaign.cpm_usd.is_not(None),
        )
        .order_by(Campaign.cpm_usd.desc())
        .limit(1)
    ).first()
    return (str(row[0]), float(row[1] or 0)) if row else None


@dataclass(frozen=True)
class Scored:
    score: int
    parts: dict[str, int]
    views_per_hour: int
    hours: float | None


def score(signal: Signal, now: datetime, cpm: float | None) -> Scored:
    hours = (
        max(1.0, (now - signal.published_at).total_seconds() / 3600)
        if signal.published_at
        else None
    )
    vph = signal.views / hours if hours else signal.views / 48
    reach = _clamp((math.log10(max(signal.views, 1)) - 4) / 2.5 * 100)
    speed = _clamp((math.log10(max(vph, 1)) - 3) / 2 * 100)
    if signal.outlier:
        outlier = _clamp((signal.outlier - 1) / 9 * 100)
    elif signal.chart_rank:
        outlier = _clamp(80 - signal.chart_rank)  # high on the trending list
    else:
        outlier = 30
    if hours is None:
        fresh = 30
    elif hours <= 6:
        fresh = 100
    elif hours <= 24:
        fresh = 80
    elif hours <= 72:
        fresh = 50
    else:
        fresh = 10
    fit = 100 if signal.keyword else 60
    money = _clamp(cpm * 25) if cpm else 0
    parts = {
        "reach": reach,
        "speed": speed,
        "outlier": outlier,
        "fresh": fresh,
        "fit": fit,
        "money": money,
    }
    total = _clamp(sum(WEIGHTS[k] * v for k, v in parts.items()))
    return Scored(total, parts, round(vph), hours)


def _num(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f} Mio.".replace(".", ",", 1)
    return f"{round(value):,}".replace(",", ".")


def _hours(hours: float) -> str:
    if hours < 48:
        n = max(1, round(hours))
        return f"{n} Stunde" if n == 1 else f"{n} Stunden"
    return f"{round(hours / 24)} Tagen"


def facts(signal: Signal, scored: Scored, campaign: tuple[str, float] | None) -> list[str]:
    out = []
    if scored.hours is not None:
        out.append(
            f"{_num(signal.views)} Aufrufe in {_hours(scored.hours)} "
            f"(rund {_num(scored.views_per_hour)} pro Stunde)"
        )
    else:
        out.append(f"{_num(signal.views)} Aufrufe")
    if signal.chart_rank and signal.region:
        out.append(f"Platz {signal.chart_rank} der YouTube-Trends in {signal.region}")
    if signal.outlier:
        who = f" bei {signal.creator}" if signal.creator else ""
        out.append(f"{signal.outlier:.1f}× so viele Aufrufe wie sonst{who}".replace(".", ",", 1))
    if signal.likes or signal.comments:
        out.append(f"{_num(signal.likes or 0)} Likes, {_num(signal.comments or 0)} Kommentare")
    if campaign:
        cpm = f"{campaign[1]:.2f}".replace(".", ",")
        out.append(f"Passende Kampagne: {campaign[0]} ({cpm} $ je 1.000 Aufrufe)")
    if signal.creator and not signal.outlier:
        out.append(f"Kanal: {signal.creator}")
    if signal.is_mock:
        out.append("Testdaten, kein echter Abruf")
    return out


# --- drafts --------------------------------------------------------------------------


def _language(project: ContentProject) -> Language:
    for code in project.languages or []:
        try:
            return Language(str(code))
        except ValueError:
            continue
    return Language.DE


def make_drafts(
    session: Session, settings: Settings, alarm: TrendAlarm, project: ContentProject
) -> list[OwnProduction]:
    """One own production per angle; raises the errors of :mod:`services.ai`."""
    language = _language(project)
    made: list[OwnProduction] = []
    for label, instruction in ANGLES[: settings.trend_alarm_drafts]:
        pitch = (
            f"{instruction} Anlass: ein Video, das gerade stark läuft "
            f"({'; '.join(alarm.facts[:2])}). Nur das Thema aufgreifen, nichts aus dem "
            "fremden Video übernehmen, keine Zahlen erfinden."
        )
        try:
            draft = own_production.draft_script(
                session,
                settings,
                project,
                topic=f"{label}: {alarm.title}"[:300],
                pitch=pitch,
                language=language,
                user_id=None,
            )
        except (ai.AIBlockedError, ai.AIRefusedError, ai.AIFailedError) as exc:
            if not made:
                raise
            alarm.error = f"Nur {len(made)} Entwürfe: {exc}"[:2000]
            break
        prod = OwnProduction(
            content_project_id=project.id,
            title=" ".join(draft.title.split())[: own_production.TITLE_MAX],
            language=language,
            status=ProductionStatus.QUEUED,
            segments=draft.segments,
            script_source=draft.provider,
            ai_call_id=draft.call_id,
        )
        session.add(prod)
        session.flush()
        made.append(prod)
    alarm.drafts = [
        {"angle": label, "production_id": p.id} for (label, _), p in zip(ANGLES, made, strict=False)
    ]
    return made


def queue_renders(productions: list[OwnProduction]) -> int:
    """Hand the drafts to the own production agent; returns how many were queued."""
    from services.orchestrator import submit

    queued = 0
    for prod in productions:
        try:
            submit("own_production", {"entity_type": "own_productions", "entity_id": prod.id})
            queued += 1
        except Exception:  # queue down: the sweep finishes the alarm later
            log.warning("trend alarm render not queued", extra={"production_id": prod.id})
    return queued


# --- scan ----------------------------------------------------------------------------


@dataclass
class ScanResult:
    signals: int = 0
    alarms: list[int] = field(default_factory=list)
    drafts: int = 0
    finished: int = 0
    expired: int = 0
    errors: list[str] = field(default_factory=list)
    mode: str = "mock"


def _today_start(settings: Settings, now: datetime) -> datetime:
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(settings.timezone)
    local = now.astimezone(tz)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def scan(
    session: Session,
    settings: Settings,
    *,
    now: datetime | None = None,
    client: httpx.Client | None = None,
    project_id: int | None = None,
    render: bool = True,
    manual: bool = False,
) -> ScanResult:
    """Look for hot topics, open alarms and start their drafts; commits."""
    now = now or datetime.now(UTC)
    result = ScanResult(mode="live" if competitors.live(settings) else "mock")
    result.finished, result.expired = sweep(session, settings, now)

    q = select(ContentProject).where(ContentProject.status == ContentProjectStatus.ACTIVE)
    if project_id is not None:
        q = q.where(ContentProject.id == project_id)
    projects = list(session.scalars(q.order_by(ContentProject.priority, ContentProject.id)))
    if not projects:
        session.commit()
        return result
    signals, result.errors = collect(session, settings, projects, now, client, include_mock=manual)
    result.signals = len(signals)

    today = int(
        session.scalar(
            select(func.count(TrendAlarm.id)).where(
                TrendAlarm.created_at >= _today_start(settings, now)
            )
        )
        or 0
    )
    budget = max(0, settings.trend_alarm_max_per_day - today)
    known = set(
        session.scalars(
            select(TrendAlarm.signal_key).where(
                TrendAlarm.signal_key.in_([s.key for s in signals] or [""])
            )
        )
    )
    by_id = {p.id: p for p in projects}
    ranked = []
    seen: set[str] = set()
    for sig in signals:
        if sig.key in known or sig.key in seen or sig.views < settings.trend_alarm_min_views:
            continue
        seen.add(sig.key)
        camp = campaign_cpm(session, sig.project_id)
        scored = score(sig, now, camp[1] if camp else None)
        if scored.score >= settings.trend_alarm_threshold:
            ranked.append((scored.score, sig, scored, camp))
    ranked.sort(key=lambda r: -r[0])

    for _, sig, scored, camp in ranked[:budget]:
        project = by_id[sig.project_id]
        alarm = TrendAlarm(
            content_project_id=project.id,
            signal_key=sig.key,
            source=sig.source,
            title=sig.title[:300],
            url=sig.url,
            creator=sig.creator,
            published_at=sig.published_at,
            metrics={
                "views": sig.views,
                "views_per_hour": scored.views_per_hour,
                "hours": round(scored.hours, 1) if scored.hours else None,
                "likes": sig.likes,
                "comments": sig.comments,
                "outlier": sig.outlier,
                "chart_rank": sig.chart_rank,
                "region": sig.region,
                "keyword": sig.keyword,
                "campaign": {"name": camp[0], "cpm_usd": camp[1]} if camp else None,
                "parts": scored.parts,
            },
            score=scored.score,
            facts=facts(sig, scored, camp),
            status="drafting",
            is_mock=sig.is_mock,
        )
        session.add(alarm)
        session.flush()
        result.alarms.append(alarm.id)
        try:  # the AI layer commits its own bookkeeping: no savepoint here
            made = make_drafts(session, settings, alarm, project)
        except (ai.AIBlockedError, ai.AIRefusedError, ai.AIFailedError) as exc:
            alarm.status = "failed"
            alarm.error = f"Entwürfe nicht möglich: {exc}"[:2000]
            _notify(session, alarm, ready=0, autopilot=[])
            continue
        except own_production.ProductionError as exc:
            alarm.status = "failed"
            alarm.error = f"Entwürfe nicht möglich: {exc.detail}"[:2000]
            _notify(session, alarm, ready=0, autopilot=[])
            continue
        result.drafts += len(made)
        session.commit()  # the worker must see the productions
        if render:
            queue_renders(made)
    session.commit()
    return result


def sweep(session: Session, settings: Settings, now: datetime) -> tuple[int, int]:
    """Finish alarms whose drafts are done (or stuck) and expire old ones."""
    finished = expired = 0
    for alarm in session.scalars(select(TrendAlarm).where(TrendAlarm.status == "drafting")):
        prods = _productions(session, alarm)
        busy = [
            p for p in prods if p.status not in (ProductionStatus.DONE, ProductionStatus.FAILED)
        ]
        if not busy or alarm.created_at <= now - DRAFT_TIMEOUT:
            finalize(session, settings, alarm)
            finished += 1
    old = session.scalars(
        select(TrendAlarm).where(
            TrendAlarm.status == "ready",
            TrendAlarm.created_at <= now - timedelta(hours=EXPIRE_HOURS),
        )
    )
    for alarm in old:
        alarm.status = "expired"
        expired += 1
    session.flush()
    return finished, expired


# --- finishing -----------------------------------------------------------------------


def _productions(session: Session, alarm: TrendAlarm) -> list[OwnProduction]:
    ids = [int(d["production_id"]) for d in alarm.drafts or [] if d.get("production_id")]
    if not ids:
        return []
    rows = {
        p.id: p for p in session.scalars(select(OwnProduction).where(OwnProduction.id.in_(ids)))
    }
    return [rows[i] for i in ids if i in rows]


def alarm_for_production(session: Session, production_id: int) -> TrendAlarm | None:
    return session.scalar(
        select(TrendAlarm)
        .where(TrendAlarm.drafts.contains([{"production_id": production_id}]))
        .with_for_update()
    )


def on_production_done(session: Session, settings: Settings, prod: OwnProduction) -> None:
    """Called by the own production agent after a render (done or failed)."""
    alarm = alarm_for_production(session, prod.id)
    if alarm is None or alarm.status != "drafting":
        return
    prods = _productions(session, alarm)
    if any(p.status not in (ProductionStatus.DONE, ProductionStatus.FAILED) for p in prods):
        return
    finalize(session, settings, alarm)


def target_channels(session: Session, project_id: int, language: Language) -> list[Channel]:
    return [
        c
        for c in session.scalars(
            select(Channel)
            .where(
                Channel.content_project_id == project_id,
                Channel.is_paused.is_(False),
                Channel.language == language,
            )
            .order_by(Channel.id)
        )
        if c.platform.code in approval.RULES and not is_placeholder(c)
    ]


def alarm_variants(session: Session, alarm_id: int) -> list[Variant]:
    return list(
        session.scalars(
            select(Variant)
            .where(Variant.concept.contains({"trend_alarm_id": alarm_id}))
            .order_by(Variant.id)
        )
    )


def finalize(session: Session, settings: Settings, alarm: TrendAlarm) -> None:
    """Prepare posts for every finished draft, run the autopilot, push to the phone."""
    angles = {int(d["production_id"]): d.get("angle") for d in alarm.drafts or []}
    ready = 0
    problems: list[str] = []
    for prod in _productions(session, alarm):
        if prod.status != ProductionStatus.DONE or prod.output_item_id is None:
            continue
        ready += 1
        channels = target_channels(session, alarm.content_project_id, prod.language)
        if not channels:
            continue
        try:  # the text suggestions commit through the AI layer: no savepoint here
            variants = approval.prepare(
                session,
                settings,
                prod.output_item_id,
                [c.id for c in channels],
                None,
                skip_unfit=True,
            )
        except approval.ApprovalError as exc:
            problems.append(str(exc))
            continue
        for v in variants:
            v.concept = {
                **(v.concept or {}),
                "trend_alarm_id": alarm.id,
                "angle": angles.get(prod.id),
                "production_id": prod.id,
            }
    session.flush()
    if ready == 0:
        alarm.status = "failed"
        alarm.error = "Kein Entwurf wurde fertig gerendert"
        _notify(session, alarm, ready=0, autopilot=[])
        return
    alarm.status = "ready"
    if problems:
        alarm.error = "; ".join(problems)[:2000]
    names = run_autopilot(session, settings, alarm)
    _notify(session, alarm, ready=ready, autopilot=names)


def _rank(order: list[int], variant: Variant) -> int:
    pid = int((variant.concept or {}).get("production_id", 0))
    return order.index(pid) if pid in order else len(order)


def run_autopilot(session: Session, settings: Settings, alarm: TrendAlarm) -> list[str]:
    """Approve the first draft on channels with the autopilot on; returns their names."""
    if not settings.trend_autopilot_enabled or alarm.score < settings.trend_autopilot_min_score:
        return []
    order = [int(d["production_id"]) for d in alarm.drafts or []]
    by_channel: dict[int, list[Variant]] = {}
    for v in alarm_variants(session, alarm.id):
        if v.status == VideoStatus.QUALITY_APPROVED:
            by_channel.setdefault(v.channel_id, []).append(v)
    names: list[str] = []
    for channel_id, variants in by_channel.items():
        channel = session.get(Channel, channel_id)
        if channel is None or not channel.trend_autopilot or channel.is_paused:
            continue
        variants.sort(key=lambda v: _rank(order, v))
        try:
            with session.begin_nested():
                approval.approve(session, variants[0], None)
                for other in variants[1:]:
                    approval.discard(session, other, None)
        except approval.ApprovalError as exc:
            alarm.error = f"Automatik bei {channel.name}: {exc}"[:2000]
            continue
        names.append(channel.name)
        alarm.approved_production_id = int((variants[0].concept or {}).get("production_id", 0))
    if names:
        alarm.autopilot = True
        alarm.decided_at = datetime.now(UTC)
        if not any(
            v.status == VideoStatus.QUALITY_APPROVED for v in alarm_variants(session, alarm.id)
        ):
            alarm.status = "approved"
    session.flush()
    return names


def _notify(session: Session, alarm: TrendAlarm, *, ready: int, autopilot: list[str]) -> None:
    lines = [f"• {f}" for f in alarm.facts or []]
    if alarm.status == "failed":
        lines.append(alarm.error or "Keine Entwürfe.")
    elif autopilot:
        lines.append(f"Automatisch freigegeben für: {', '.join(autopilot)}.")
    else:
        lines.append(f"{ready} Entwürfe bereit. Tippen, ansehen und mit einem Tipp freigeben.")
    level = NotificationLevel.CRITICAL if alarm.score >= 90 else NotificationLevel.WARNING
    notify.add(
        session,
        f"Trend-Alarm ({alarm.score}): {alarm.title}"[:200],
        "\n".join(lines),
        level=level,
        kind="trend",
        link=f"/trend-alarm?alarm={alarm.id}",
        dedup_key=f"trend-alarm-{alarm.id}",
    )
    alarm.notified_at = datetime.now(UTC)


# --- decisions -----------------------------------------------------------------------


def approve_draft(
    session: Session, alarm: TrendAlarm, production_id: int, user_id: int | None
) -> list[Variant]:
    """One tap: approve this draft on every channel, discard the other drafts."""
    if alarm.status not in ("ready", "approved"):
        raise TrendAlarmError("Dieser Alarm wartet nicht auf eine Freigabe")
    ids = [int(d["production_id"]) for d in alarm.drafts or []]
    if production_id not in ids:
        raise TrendAlarmError("Dieser Entwurf gehört nicht zum Alarm", 404)
    approved: list[Variant] = []
    for v in alarm_variants(session, alarm.id):
        if v.status != VideoStatus.QUALITY_APPROVED:
            continue
        if int((v.concept or {}).get("production_id", 0)) == production_id:
            approval.approve(session, v, user_id)
            approved.append(v)
        else:
            approval.discard(session, v, user_id)
    if not approved and not alarm.autopilot:
        raise TrendAlarmError(
            "Kein freigabebereiter Beitrag: Es gibt im Themenbereich keinen passenden, "
            "nicht pausierten Kanal. Das Video liegt in der Mediathek."
        )
    alarm.status = "approved"
    alarm.approved_production_id = production_id
    alarm.decided_at = datetime.now(UTC)
    alarm.decided_by_user_id = user_id
    session.flush()
    return approved


def dismiss(session: Session, alarm: TrendAlarm, user_id: int | None) -> None:
    if alarm.status in ("dismissed", "approved"):
        raise TrendAlarmError("Über diesen Alarm wurde schon entschieden")
    for v in alarm_variants(session, alarm.id):
        if v.status == VideoStatus.QUALITY_APPROVED:
            approval.discard(session, v, user_id)
    for prod in _productions(session, alarm):
        if prod.status == ProductionStatus.QUEUED:  # not started yet: skip the render
            prod.status = ProductionStatus.DRAFT
    alarm.status = "dismissed"
    alarm.decided_at = datetime.now(UTC)
    alarm.decided_by_user_id = user_id
    session.flush()
