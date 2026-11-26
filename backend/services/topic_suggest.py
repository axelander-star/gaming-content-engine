"""Topic suggestions from current trends ("Themen vorschlagen").

The operator often has no idea which topic to start with. One click collects
what is in demand right now and proposes eight topic areas, each with the
numbers behind it. Germany (the first region) counts most; gaming and
entertainment always get a place when they trend:

* YouTube charts (``videos.list chart=mostPopular``, 1 quota unit per call) per
  region (``TREND_ALARM_REGIONS``, default DE and US), overall and for each
  usable video category: how many trending videos, their median views, how fast
  they grow (views per hour since upload), how many different channels share
  the chart (a crowded chart means strong competition), frequent title words;
* Wikipedia's most read articles of yesterday in German and English
  (Wikimedia REST API ``metrics/pageviews/top``, free, no key): what people
  look up right now.

The AI turns the numbers into topic areas (name, sub-topics, audience, tone,
reason, facts). Without AI the strongest categories become suggestions with a
template text. Live data needs ``YOUTUBE_API_KEY`` and ``TREND_SOURCES_MODE=live``;
otherwise development shows sample data and production shows a hint instead of
invented numbers. Music is left out: its rights rule out own short videos.
"""

from __future__ import annotations

import json
import logging
import statistics
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import ContentProjectStatus
from models.projects import ContentProject
from services import ai, competitors, quota
from services.name_research import _STOP, _WORD
from services.sources.base import QuotaExceededError

log = logging.getLogger("topic_suggest")

#: YouTube's standard video categories (``videoCategories.list``) that suit own
#: short videos, with German labels. 10 (music) is left out on purpose.
CATEGORIES: dict[str, str] = {
    "1": "Film & Animation",
    "2": "Autos & Fahrzeuge",
    "15": "Tiere",
    "17": "Sport",
    "19": "Reisen & Events",
    "20": "Gaming",
    "22": "Menschen & Blogs",
    "23": "Comedy",
    "24": "Unterhaltung",
    "25": "Nachrichten & Politik",
    "26": "Praktische Tipps & Styling",
    "27": "Bildung",
    "28": "Wissenschaft & Technik",
}
CHART_SIZE = 50
SUGGESTIONS = 8
#: always among the suggestions when they trend (unless the area already exists):
#: gaming and entertainment are the operator's home ground
FOCUS = ("20", "24")
#: the first region (Germany by default) counts fully, the others less
OTHER_REGION_WEIGHT = 0.6
REGION_NAMES = {
    "DE": "Deutschland",
    "AT": "Österreich",
    "CH": "Schweiz",
    "US": "USA",
    "GB": "Großbritannien",
}
WIKI_TOP = 25
WIKI_URL = "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/{project}/all-access/{day}"
#: Wikimedia asks every client to identify itself; generic name, no personal data.
USER_AGENT = "ContentEngine/1.0 (topic research; python-httpx)"
_WIKI_SKIP = ("Spezial:", "Special:", "Wikipedia:", "Datei:", "File:", "Hauptseite", "Main_Page")

#: Replaced by tests with ``httpx.MockTransport``; ``None`` = real network.
TRANSPORT: httpx.BaseTransport | None = None


@dataclass
class CategoryStat:
    category_id: str
    label: str
    region: str
    videos: int
    median_views: int
    views_per_hour: int
    channels: int
    words: list[str]
    examples: list[str]
    #: places in the region's overall top 50 (all categories together)
    overall: int = 0

    def fact(self) -> str:
        where = REGION_NAMES.get(self.region, self.region)
        text = (
            f"{self.label} ({where}): {self.videos} der {CHART_SIZE} meistgesehenen Videos, "
            f"Median {_n(self.median_views)} Aufrufe, {_n(self.views_per_hour)} Aufrufe pro "
            f"Stunde, {self.channels} verschiedene Kanäle"
        )
        if self.overall:
            text += f", {self.overall} Plätze in den Top {CHART_SIZE} insgesamt"
        return text


def _n(value: int) -> str:
    """German thousands separator: 100000 -> 100.000."""
    return f"{value:,}".replace(",", ".")


@dataclass
class Suggestion:
    name: str
    description: str
    subtopics: list[str]
    audience: str
    tone: str
    reason: str
    facts: list[str]
    examples: list[str] = field(default_factory=list)
    score: int = 0


@dataclass
class Result:
    live: bool
    sample: bool
    suggestions: list[Suggestion]
    sources: list[str]
    hint: str | None = None
    errors: list[str] = field(default_factory=list)
    generated_at: str = ""
    provider: str = "template"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# --- collecting -------------------------------------------------------------------


def _hours_since(value: Any, now: datetime) -> float:
    try:
        published = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return 24.0
    return max(1.0, (now - published).total_seconds() / 3600)


def stats_for(
    raw: list[dict[str, Any]], category_id: str, region: str, now: datetime
) -> CategoryStat | None:
    """Aggregate one chart (already limited to one category) into numbers."""
    views: list[int] = []
    speed: list[int] = []
    channels: set[str] = set()
    titles: list[str] = []
    for video in raw:
        snippet = video.get("snippet") or {}
        stats = video.get("statistics") or {}
        try:
            count = int(str(stats.get("viewCount")))
        except (TypeError, ValueError):
            continue
        views.append(count)
        speed.append(round(count / _hours_since(snippet.get("publishedAt"), now)))
        channels.add(str(snippet.get("channelId") or snippet.get("channelTitle") or ""))
        titles.append(" ".join(str(snippet.get("title") or "").split()))
    if not views:
        return None
    counts: Counter[str] = Counter()
    for title in titles:
        # once per title, in title order, so ties keep a stable order
        counts.update(
            list(dict.fromkeys(w.lower() for w in _WORD.findall(title) if w.lower() not in _STOP))
        )
    return CategoryStat(
        category_id=category_id,
        label=CATEGORIES.get(category_id, category_id),
        region=region,
        videos=len(views),
        median_views=int(statistics.median(views)),
        views_per_hour=int(statistics.median(speed)),
        channels=len(channels - {""}),
        words=[w for w, n in counts.most_common(8) if n >= 2],
        examples=[t[:120] for t in titles[:3] if t],
    )


def _chart(
    http: httpx.Client, settings: Settings, region: str, category: str | None
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


def regions_of(settings: Settings) -> list[str]:
    regions = [r.strip().upper() for r in settings.trend_alarm_regions.split(",") if r.strip()]
    return regions[:3] or ["DE"]


def youtube_stats(
    settings: Settings, redis: Redis, http: httpx.Client, now: datetime, errors: list[str]
) -> list[CategoryStat]:
    """Per region: the overall chart first, then one chart per category.

    Some category charts are missing in some regions (YouTube answers 404, gaming
    often among them) or come back empty. Then the videos of that category in the
    overall chart stand in, so gaming and entertainment are still rated."""
    out: list[CategoryStat] = []
    for region in regions_of(settings):
        groups: dict[str, list[dict[str, Any]]] = {}
        try:
            quota.consume(redis, "youtube", 1, settings.youtube_daily_quota_units)
            for video in _chart(http, settings, region, None):
                category = str((video.get("snippet") or {}).get("categoryId") or "")
                groups.setdefault(category, []).append(video)
        except QuotaExceededError:
            errors.append("YouTube-Tageskontingent erreicht")
            return out
        except (competitors.RadarError, httpx.HTTPError, ValueError) as exc:
            errors.append(f"YouTube {region}/gesamt: {exc}"[:200])
        for category in CATEGORIES:
            raw: list[dict[str, Any]] = []
            try:
                quota.consume(redis, "youtube", 1, settings.youtube_daily_quota_units)
                raw = _chart(http, settings, region, category)
            except QuotaExceededError:
                errors.append("YouTube-Tageskontingent erreicht")
                return out
            except (competitors.RadarError, httpx.HTTPError, ValueError) as exc:
                # some categories have no chart in some regions (404): not an error
                if "404" not in str(exc):
                    errors.append(f"YouTube {region}/{CATEGORIES[category]}: {exc}"[:200])
            in_overall = groups.get(category) or []
            if len(raw) < 2:
                raw = in_overall
            stat = stats_for(raw, category, region, now)
            if stat is not None:
                stat.overall = len(in_overall)
                out.append(stat)
    return out


def wikipedia_top(http: httpx.Client, now: datetime, errors: list[str]) -> list[tuple[str, int]]:
    """Most read articles of yesterday (German and English Wikipedia)."""
    day = (now - timedelta(days=1)).strftime("%Y/%m/%d")
    out: list[tuple[str, int]] = []
    for project in ("de.wikipedia", "en.wikipedia"):
        try:
            res = http.get(
                WIKI_URL.format(project=project, day=day), headers={"User-Agent": USER_AGENT}
            )
            res.raise_for_status()
            items = ((res.json().get("items") or [{}])[0]).get("articles") or []
        except (httpx.HTTPError, ValueError, AttributeError, IndexError) as exc:
            errors.append(f"Wikipedia {project}: {type(exc).__name__}")
            continue
        taken = 0
        for item in items:
            title = str(item.get("article") or "")
            if not title or title.startswith(_WIKI_SKIP):
                continue
            out.append((title.replace("_", " "), int(item.get("views") or 0)))
            taken += 1
            if taken >= WIKI_TOP:
                break
    return out


# --- scoring and texts ------------------------------------------------------------


def _scores(stats: list[CategoryStat], home: str) -> list[float]:
    """Score per stat: growth within its own region, chart places, a chart shared
    by many channels, places in the overall chart. The home region counts fully,
    other regions less, so US numbers do not drown out Germany."""
    top_speed: dict[str, int] = {}
    for s in stats:
        top_speed[s.region] = max(top_speed.get(s.region, 0), s.views_per_hour)
    out: list[float] = []
    for s in stats:
        speed = s.views_per_hour / (top_speed[s.region] or 1)
        crowd = s.channels / max(s.videos, 1)  # 1.0 = every video another channel
        score = (
            45 * speed
            + 20 * min(s.videos, CHART_SIZE) / CHART_SIZE
            + 15 * crowd
            + 20 * min(s.overall, 10) / 10
        )
        out.append(score * (1.0 if s.region == home else OTHER_REGION_WEIGHT))
    return out


def rank(stats: list[CategoryStat], home: str | None = None) -> list[CategoryStat]:
    """Best stat per category, strongest first (home region preferred)."""
    if not stats:
        return []
    home = home or stats[0].region
    best: dict[str, tuple[float, CategoryStat]] = {}
    for score, s in zip(_scores(stats, home), stats, strict=True):
        if s.label not in best or score > best[s.label][0]:
            best[s.label] = (score, s)
    return [s for _, s in sorted(best.values(), key=lambda x: -x[0])]


def pick(stats: list[CategoryStat], taken: set[str], home: str | None = None) -> list[CategoryStat]:
    """Top categories; gaming and entertainment always get a place when they trend."""
    ranked = [s for s in rank(stats, home) if s.label.lower() not in taken]
    picked = ranked[:SUGGESTIONS]
    for s in ranked[SUGGESTIONS:]:
        if s.category_id not in FOCUS:
            continue
        for j in range(len(picked) - 1, 0, -1):  # the strongest one always stays
            if picked[j].category_id not in FOCUS:
                picked[j] = s
                break
    return sorted(picked, key=ranked.index)


def _facts(stats: list[CategoryStat], label: str, home: str) -> list[str]:
    """All regions of one category, home region first."""
    rows = sorted((s for s in stats if s.label == label), key=lambda s: s.region != home)
    return [s.fact() for s in rows][:3]


def template(
    stats: list[CategoryStat], taken: set[str], home: str | None = None
) -> list[Suggestion]:
    home = home or (stats[0].region if stats else "DE")
    out: list[Suggestion] = []
    for i, s in enumerate(pick(stats, taken, home)):
        words = [w.capitalize() for w in s.words[:5]]
        where = REGION_NAMES.get(s.region, s.region)
        out.append(
            Suggestion(
                name=s.label,
                description=f"Kurzvideos rund um {s.label}, ausgerichtet an dem, was gerade läuft.",
                subtopics=words,
                audience="",
                tone="locker",
                reason=(
                    f"Wächst gerade schnell: {_n(s.views_per_hour)} Aufrufe pro Stunde im Median "
                    f"in den Trends für {where}."
                ),
                facts=_facts(stats, s.label, home),
                examples=s.examples,
                score=max(0, 100 - i * 8),
            )
        )
    return out


SYSTEM = (
    "You suggest topic areas for new short-video channels (YouTube Shorts, TikTok, "
    "Instagram Reels) of one operator in Germany who produces his own videos. The German "
    "audience comes first: numbers from Germany (DE) weigh most, other regions only "
    "show where a topic is heading. Gaming and entertainment are his home ground: when "
    "they appear in the data, include at least one suggestion for each (a concrete game, "
    "series or format is better than the bare category). Use only the numbers "
    "given; never invent figures. Prefer topics with lasting demand that are rising now, "
    "that one person can produce without licensed footage, and where the chart is not "
    "owned by a few big channels. No music, no politics or adult topics. Answer in "
    "German with JSON only."
)


def _prompt(
    stats: list[CategoryStat], wiki: list[tuple[str, int]], taken: set[str], home: str
) -> str:
    ordered = sorted(stats, key=lambda s: s.region != home)  # home region first
    lines = [s.fact() + (f"; Begriffe: {', '.join(s.words)}" if s.words else "") for s in ordered]
    hot = ", ".join(f"{t} ({v:,})".replace(",", ".") for t, v in wiki[:30]) or "-"
    return (
        f"Heimatmarkt: {REGION_NAMES.get(home, home)}. "
        "YouTube-Trends je Kategorie und Region (Stand jetzt):\n- "
        + "\n- ".join(lines)
        + f"\n\nMeistgelesene Wikipedia-Artikel gestern (Aufrufe): {hot}\n"
        "Schon vorhandene Themenbereiche (nicht vorschlagen): "
        f"{', '.join(sorted(taken)) or '-'}\n\n"
        f"Schlage {SUGGESTIONS} Themenbereiche vor. JSON: "
        '{"suggestions": [{"name": "max 40 Zeichen", "description": "1 Satz", '
        '"subtopics": ["3-6 Unterthemen"], "audience": "Zielgruppe", "tone": "Tonalität", '
        '"reason": "2 Sätze warum jetzt", "facts": ["Zahlen aus den Daten oben"], '
        '"score": 0-100}]}'
    )


def _parse(text: str) -> list[dict[str, Any]]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except ValueError:
        return []
    raw = data.get("suggestions") if isinstance(data, dict) else None
    return [r for r in raw if isinstance(r, dict)] if isinstance(raw, list) else []


def _strs(value: Any, limit: int, size: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [" ".join(str(v).split())[:size] for v in value if str(v).strip()][:limit]


def from_ai(
    session: Session,
    settings: Settings,
    stats: list[CategoryStat],
    wiki: list[tuple[str, int]],
    taken: set[str],
    user_id: int | None,
    home: str = "DE",
) -> tuple[list[Suggestion], str]:
    fallback = template(stats, taken, home)
    mock = json.dumps({"suggestions": [asdict(s) for s in fallback]}, ensure_ascii=False)
    try:
        result = ai.generate(
            session,
            settings,
            ai.AIRequest(
                purpose="topic_suggestions",
                tier="text",
                messages=[ai.AIMessage("user", _prompt(stats, wiki, taken, home))],
                system=SYSTEM,
                max_tokens=3000,
                mock=lambda _req: mock,
                user_id=user_id,
            ),
        )
    except ai.AIError as exc:
        log.info("topic suggestions from template (%s)", exc.code)
        return fallback, "template"
    examples = {s.label.lower(): s.examples for s in stats}
    out: list[Suggestion] = []
    for raw in _parse(result.text):
        name = " ".join(str(raw.get("name") or "").split())[:60]
        if len(name) < 3 or name.lower() in taken or any(s.name == name for s in out):
            continue
        try:
            score = max(0, min(100, int(raw.get("score") or 0)))
        except (TypeError, ValueError):
            score = 0
        out.append(
            Suggestion(
                name=name,
                description=" ".join(str(raw.get("description") or "").split())[:300],
                subtopics=_strs(raw.get("subtopics"), 6, 60),
                audience=" ".join(str(raw.get("audience") or "").split())[:200],
                tone=" ".join(str(raw.get("tone") or "").split())[:100],
                reason=" ".join(str(raw.get("reason") or "").split())[:500],
                facts=_strs(raw.get("facts"), 4, 300),
                examples=examples.get(name.lower(), []),
                score=score,
            )
        )
    if not out:
        return fallback, "template"
    out.sort(key=lambda s: -s.score)
    return out[:SUGGESTIONS], result.provider


# --- sample data (development only) ---------------------------------------------


def sample_stats(now: datetime) -> list[CategoryStat]:
    rows = [
        ("26", "DE", 7, 180_000, 4_200, 7, ["rezepte", "airfryer", "schnell"]),
        ("28", "DE", 5, 240_000, 3_900, 5, ["handy", "akku", "trick"]),
        ("15", "US", 6, 410_000, 6_100, 6, ["dog", "rescue", "cute"]),
        ("27", "DE", 4, 95_000, 2_100, 4, ["geschichte", "fakten", "erklärt"]),
        ("17", "DE", 8, 300_000, 5_000, 6, ["tor", "highlights", "bundesliga"]),
        ("2", "US", 3, 150_000, 1_800, 3, ["tesla", "test", "review"]),
        ("20", "DE", 9, 220_000, 4_600, 8, ["minecraft", "fortnite", "update"]),
        ("24", "DE", 6, 350_000, 5_400, 6, ["challenge", "reaction", "show"]),
        ("23", "DE", 4, 120_000, 2_500, 4, ["sketch", "comedy", "alltag"]),
    ]
    return [
        CategoryStat(c, CATEGORIES[c], r, n, med, vph, ch, words, [f"Beispielvideo {c}-{i}"])
        for c, r, n, med, vph, ch, words in rows
        for i in (1,)
    ]  # fixed numbers, marked as sample data in the dashboard


# --- entry point ------------------------------------------------------------------


def suggest(
    session: Session,
    settings: Settings,
    redis: Redis,
    *,
    user_id: int | None = None,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> Result:
    now = now or datetime.now(UTC)
    taken = {
        n.lower()
        for n in session.scalars(
            select(ContentProject.name).where(
                ContentProject.status != ContentProjectStatus.ARCHIVED
            )
        )
    }
    errors: list[str] = []
    live = competitors.live(settings)
    if live:
        own = client is None
        http = client or httpx.Client(timeout=settings.http_timeout_s, transport=TRANSPORT)
        try:
            stats = youtube_stats(settings, redis, http, now, errors)
            wiki = wikipedia_top(http, now, errors)
        finally:
            if own:
                http.close()
        sources = ["YouTube-Trends", "Wikipedia (meistgelesen)"]
        sample = False
    elif settings.sample_data_enabled:
        stats, wiki, sources, sample = sample_stats(now), [("Beispielartikel", 1000)], [], True
    else:
        return Result(
            live=False,
            sample=False,
            suggestions=[],
            sources=[],
            hint=(
                "Für Vorschläge aus echten Trends braucht der Server einen YouTube-Schlüssel: "
                "YOUTUBE_API_KEY und TREND_SOURCES_MODE=live in der .env eintragen."
            ),
            generated_at=now.isoformat(),
        )
    if not stats:
        return Result(
            live=live,
            sample=sample,
            suggestions=[],
            sources=sources,
            hint="Gerade keine Trenddaten erhalten. Bitte später erneut versuchen.",
            errors=errors,
            generated_at=now.isoformat(),
        )
    home = regions_of(settings)[0]
    suggestions, provider = from_ai(session, settings, stats, wiki, taken, user_id, home)
    return Result(
        live=live,
        sample=sample,
        suggestions=suggestions,
        sources=sources,
        errors=errors[:5],
        generated_at=now.isoformat(),
        provider=provider,
    )
