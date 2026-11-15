"""Research feeds (extension phase E5): fetch RSS/Atom safely, store items.

Mock mode (default) never touches the network: every topic area gets fixed
sample feeds built from its sub-topics, parsed by the same parser.

Live mode fetches only ``http``/``https`` URLs on public addresses (no loopback,
private or link-local targets, also after redirects), with a size limit and a
timeout. XML is parsed with ``defusedxml`` (no entity expansion, no external
entities). Feed text is foreign content: it is stored and shown as data.
"""

from __future__ import annotations

import hashlib
import html
import ipaddress
import re
import socket
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin, urlsplit
from xml.etree.ElementTree import Element

import httpx
from defusedxml import ElementTree as SafeET
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import ContentProjectStatus
from models.projects import ContentProject
from models.research import ResearchItem, ResearchSource

MAX_TITLE = 500
MAX_SUMMARY = 1000
MAX_REDIRECTS = 3
USER_AGENT = "ContentEngine-Research/1.0 (+private feed reader)"
ACCEPT = "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8"


class FeedError(Exception):
    """A feed could not be fetched or parsed (German message)."""


@dataclass(frozen=True)
class FeedEntry:
    guid: str
    title: str
    url: str | None
    summary: str | None
    published_at: datetime | None


# --- parsing -------------------------------------------------------------------------

_TAG = re.compile(r"<[^>]+>")
_ATOM = "{http://www.w3.org/2005/Atom}"


def clean_text(value: str | None, limit: int) -> str | None:
    """Strip markup and whitespace; foreign HTML never reaches the dashboard as HTML."""
    if not value:
        return None
    text = html.unescape(_TAG.sub(" ", value))
    text = " ".join(text.split())
    return text[:limit] or None


def _date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        parsed = parsedate_to_datetime(value)  # RSS (RFC 822)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))  # Atom (RFC 3339)
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _safe_url(value: str | None, base: str | None = None) -> str | None:
    if not value:
        return None
    url = urljoin(base, value.strip()) if base else value.strip()
    return url[:1000] if urlsplit(url).scheme in ("http", "https") else None


def _text(el: Element | None) -> str | None:
    return None if el is None else "".join(el.itertext())


def parse_feed(data: bytes, base_url: str | None = None) -> list[FeedEntry]:
    """Parse RSS 2.0 or Atom 1.0 into entries (newest first as given by the feed)."""
    try:
        root = SafeET.fromstring(data)
    except Exception as exc:  # defusedxml raises its own errors for forbidden constructs
        raise FeedError(f"Kein gültiger Feed ({type(exc).__name__})") from None
    entries: list[FeedEntry] = []
    if root.tag == "rss" or root.find("channel") is not None:
        for item in root.iter("item"):
            title = clean_text(_text(item.find("title")), MAX_TITLE)
            link = _safe_url(_text(item.find("link")), base_url)
            guid = (_text(item.find("guid")) or link or title or "").strip()
            if not title or not guid:
                continue
            entries.append(
                FeedEntry(
                    guid=guid,
                    title=title,
                    url=link,
                    summary=clean_text(_text(item.find("description")), MAX_SUMMARY),
                    published_at=_date(_text(item.find("pubDate"))),
                )
            )
    elif root.tag == f"{_ATOM}feed":
        for entry in root.iter(f"{_ATOM}entry"):
            title = clean_text(_text(entry.find(f"{_ATOM}title")), MAX_TITLE)
            link_el = entry.find(f"{_ATOM}link[@rel='alternate']")
            if link_el is None:
                link_el = entry.find(f"{_ATOM}link")
            link = _safe_url(link_el.get("href") if link_el is not None else None, base_url)
            guid = (_text(entry.find(f"{_ATOM}id")) or link or title or "").strip()
            if not title or not guid:
                continue
            summary = _text(entry.find(f"{_ATOM}summary")) or _text(entry.find(f"{_ATOM}content"))
            published = _text(entry.find(f"{_ATOM}published")) or _text(
                entry.find(f"{_ATOM}updated")
            )
            entries.append(
                FeedEntry(guid, title, link, clean_text(summary, MAX_SUMMARY), _date(published))
            )
    else:
        raise FeedError("Weder RSS noch Atom")
    return entries


# --- fetching ------------------------------------------------------------------------


def check_public_url(url: str, resolve: Callable[[str], list[str]] | None = None) -> None:
    """Refuse non-http(s) URLs and hosts that resolve to non-public addresses (SSRF)."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise FeedError("Nur http- und https-Adressen sind erlaubt")
    if parts.username or parts.password:
        raise FeedError("Adressen mit Zugangsdaten sind nicht erlaubt")
    resolver = resolve or _resolve
    try:
        addresses = resolver(parts.hostname)
    except OSError:
        raise FeedError(f"Adresse {parts.hostname} nicht auflösbar") from None
    if not addresses:
        raise FeedError(f"Adresse {parts.hostname} nicht auflösbar")
    for addr in addresses:
        ip = ipaddress.ip_address(addr)
        if not ip.is_global or ip.is_multicast:
            raise FeedError("Interne oder private Adressen sind nicht erlaubt")


def _resolve(host: str) -> list[str]:
    return sorted({str(info[4][0]) for info in socket.getaddrinfo(host, None)})


Fetcher = Callable[[str, Settings], bytes]


def fetch_url(url: str, settings: Settings) -> bytes:
    """Download a feed with redirect, size and address checks."""
    current = url
    with httpx.Client(
        timeout=settings.http_timeout_s,
        follow_redirects=False,
        headers={"User-Agent": USER_AGENT, "Accept": ACCEPT},
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            check_public_url(current)
            try:
                with client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise FeedError("Weiterleitung ohne Ziel")
                        current = urljoin(current, location)
                        continue
                    if response.status_code != 200:
                        raise FeedError(f"HTTP {response.status_code}")
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > settings.research_max_feed_bytes:
                            raise FeedError("Feed ist zu groß")
                    return bytes(body)
            except httpx.HTTPError as exc:
                raise FeedError(f"Abruf fehlgeschlagen ({type(exc).__name__})") from None
    raise FeedError("Zu viele Weiterleitungen")


fetcher: Fetcher = fetch_url  # replaced in tests


# --- mock feeds ----------------------------------------------------------------------

_MOCK_HEADLINES = (
    "{t}: Was diese Woche neu ist",
    "Fünf Fehler bei {t}, die fast alle machen",
    "{t} im Test: Lohnt sich der Hype?",
    "Neue Studie zu {t} sorgt für Diskussionen",
    "{t} für Einsteiger: der schnelle Überblick",
    "Warum gerade alle über {t} reden",
)


def mock_feed(project: ContentProject, source_name: str, now: datetime) -> bytes:
    """A fixed RSS feed for a topic area (deterministic per day)."""
    topics = [str(t) for t in project.subtopics or []] or [project.name]
    items = []
    for i, template in enumerate(_MOCK_HEADLINES):
        topic = topics[i % len(topics)]
        title = template.format(t=topic)
        day = now.date().isoformat()
        guid = f"mock:{project.slug}:{source_name}:{day}:{i}"
        published = (now - timedelta(hours=3 + 7 * i)).strftime("%a, %d %b %Y %H:%M:%S +0000")
        items.append(
            f"<item><title>{html.escape(title)}</title>"
            f"<link>https://example.invalid/{project.slug}/{day}/{i}</link>"
            f"<guid>{html.escape(guid)}</guid><pubDate>{published}</pubDate>"
            f"<description>Testeintrag ({html.escape(source_name)}) zum Thema "
            f"{html.escape(topic)}. Keine echte Quelle.</description></item>"
        )
    return (
        '<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel>'
        f"<title>{html.escape(source_name)}</title>{''.join(items)}</channel></rss>"
    ).encode()


# --- storing -------------------------------------------------------------------------


def _hash(guid: str) -> str:
    return hashlib.sha256(guid.encode()).hexdigest()


def store_entries(
    session: Session,
    project: ContentProject,
    source: ResearchSource | None,
    entries: list[FeedEntry],
    *,
    is_mock: bool,
    limit: int,
) -> int:
    """Insert new entries (duplicates are skipped); returns how many were new."""
    new = 0
    for entry in entries[:limit]:
        result = session.execute(
            pg_insert(ResearchItem)
            .values(
                content_project_id=project.id,
                source_id=source.id if source else None,
                guid_hash=_hash(entry.guid),
                title=entry.title,
                url=entry.url,
                summary=entry.summary,
                published_at=entry.published_at,
                is_mock=is_mock,
            )
            .on_conflict_do_nothing(constraint="uq_research_items_project_guid")
            .returning(ResearchItem.id)
        )
        if result.scalar() is not None:
            new += 1
    return new


@dataclass
class ProjectResult:
    project: str
    sources: int
    new_items: int
    errors: list[str]


def collect(
    session: Session, settings: Settings, project: ContentProject, now: datetime | None = None
) -> ProjectResult:
    """Fetch all enabled feeds of one topic area and store new items."""
    now = now or datetime.now(UTC)
    mock = settings.research_sources_mode == "mock"
    sources = list(
        session.scalars(
            select(ResearchSource)
            .where(
                ResearchSource.content_project_id == project.id,
                ResearchSource.enabled.is_(True),
            )
            .order_by(ResearchSource.id)
        )
    )
    limit = settings.research_items_per_source
    result = ProjectResult(project.name, len(sources), 0, [])
    if mock and not sources:
        entries = parse_feed(mock_feed(project, "Beispiel-Feed", now))
        added = store_entries(session, project, None, entries, is_mock=True, limit=limit)
        result.new_items += added
        return result
    for source in sources:
        source.last_fetched_at = now
        try:
            data = mock_feed(project, source.name, now) if mock else fetcher(source.url, settings)
            entries = parse_feed(data, source.url)
        except FeedError as exc:
            source.last_status = "error"
            source.last_error = str(exc)[:1000]
            source.last_item_count = 0
            result.errors.append(f"{source.name}: {exc}")
            continue
        added = store_entries(session, project, source, entries, is_mock=mock, limit=limit)
        source.last_status = "mock" if mock else "ok"
        source.last_error = None
        source.last_item_count = len(entries)
        result.new_items += added
    session.flush()
    return result


def active_projects(session: Session, project_id: int | None = None) -> list[ContentProject]:
    query = select(ContentProject).where(ContentProject.status == ContentProjectStatus.ACTIVE)
    if project_id is not None:
        query = query.where(ContentProject.id == project_id)
    return list(session.scalars(query.order_by(ContentProject.priority, ContentProject.id)))


def recent_items(
    session: Session, project_id: int, *, unused_only: bool = True, days: int = 7, limit: int = 40
) -> list[ResearchItem]:
    since = datetime.now(UTC) - timedelta(days=days)
    query = select(ResearchItem).where(
        ResearchItem.content_project_id == project_id, ResearchItem.fetched_at >= since
    )
    if unused_only:
        query = query.where(ResearchItem.used_at.is_(None))
    query = query.order_by(
        ResearchItem.published_at.desc().nulls_last(), ResearchItem.id.desc()
    ).limit(limit)
    return list(session.scalars(query))


def item_dict(item: ResearchItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "title": item.title,
        "url": item.url,
        "summary": item.summary,
        "published_at": item.published_at.isoformat() if item.published_at else None,
    }
