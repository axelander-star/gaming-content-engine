"""Ausbau A7: natural hooks, hook A/B tests, winner recycling."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import get_settings
from core.enums import (
    AgentRunStatus,
    Language,
    MetricWindow,
    PublishingJobStatus,
    PublishingMode,
    UserRole,
    VideoStatus,
)
from models import User
from models.access import Notification
from models.analytics import Metric
from models.production import Variant
from models.publishing import Post, PublishingJob
from models.research import Idea
from services import creative, hooks, orchestrator, winners
from tests.conftest import login
from tests.factories import build_chain

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)


# --- natural hooks ---------------------------------------------------------------------


def test_cliches_caps_emoji_and_shouting_are_caught() -> None:
    assert hooks.problems("Du wirst nicht glauben, was hier passiert", Language.DE)
    assert hooks.problems("Der krasseste Moment ever", Language.DE)
    assert hooks.problems("You won't believe this insane play", Language.EN)
    assert hooks.problems("Watch THIS", Language.EN) == ["Wort in Großbuchstaben"]
    assert hooks.problems("Was passiert hier?!!", Language.DE) == ["zu viele Ausrufezeichen"]
    assert hooks.problems("Schau mal 🔥", Language.DE) == ["Emoji im gesprochenen Hook"]
    assert hooks.problems(" ".join(["Wort"] * 20), Language.DE)
    assert hooks.natural("Hättest du das in Valorant kommen sehen?", Language.DE)


def test_every_template_hook_is_natural() -> None:
    for language, by_type in hooks.POOL.items():
        assert set(by_type) == set(creative.HOOK_TYPES)
        for options in by_type.values():
            assert len(options) >= 3
            for option in options:
                text = option.format(g="Valorant")
                assert hooks.natural(text, language), (text, hooks.problems(text, language))


def test_recent_hooks_of_the_channel_are_not_repeated() -> None:
    def draft(avoid: set[str]) -> str:
        return creative.write_script(
            language=Language.DE, video_format="surprise", hook_type="question",
            game="Valorant", source_name="Test", duration_s=30.0, seed="1:2:A", avoid=avoid,
        ).hook  # fmt: skip

    first = draft(set())
    second = draft({first})
    assert second != first
    third = draft({first, second})
    assert third not in {first, second}
    # all used: the stable choice comes back instead of failing
    every = {o.format(g="Valorant") for o in hooks.POOL[Language.DE]["question"]}
    assert draft(every) == first


# --- hook tests and winners ------------------------------------------------------------


def _post(db: Session, v: Variant, views: int, age: timedelta) -> Post:
    v.status = VideoStatus.PUBLISHED
    job = PublishingJob(
        variant_id=v.id, channel_id=v.channel_id, status=PublishingJobStatus.SUCCEEDED,
        mode=PublishingMode.MOCK, scheduled_for=NOW - age, idempotency_key=f"w-{v.id}-{age}",
    )  # fmt: skip
    db.add(job)
    db.flush()
    post = Post(
        publishing_job_id=job.id, variant_id=v.id, channel_id=v.channel_id,
        external_post_id=f"mock-{v.id}", published_at=NOW - age, is_mock=True,
    )  # fmt: skip
    db.add(post)
    db.flush()
    db.add(Metric(post_id=post.id, measure_window=MetricWindow.H48, views=views, measured_at=NOW))
    db.flush()
    return post


def _history(db: Session, n: int = 6) -> int:
    """``n`` ordinary posts (1,000 views) on the first German channel; its id."""
    channel_id = 0
    for i in range(n):
        chain = build_chain(db)
        chain.variant.title, chain.variant.hook_type = f"Normal {i}", "question"
        _post(db, chain.variant, 1000, timedelta(days=30 - i))
        channel_id = chain.channel.id
    return channel_id


def _ab(db: Session, views_a: int, views_b: int, age: timedelta) -> tuple[Variant, Variant]:
    chain = build_chain(db)
    a = chain.variant
    a.title, a.hook_type, a.video_format = "Clutch in Runde 13", "question", "surprise"
    chain.clip.storage_uri, chain.clip.sha256 = "local://clips/c.mp4", "f" * 64
    b = Variant(
        clip_id=a.clip_id, channel_id=a.channel_id, content_project_id=a.content_project_id,
        language=a.language, variant_label="B", hook_type="countdown", video_format="surprise",
        title="Clutch in Runde 13 (B)",
    )  # fmt: skip
    db.add(b)
    db.flush()
    _post(db, a, views_a, age)
    _post(db, b, views_b, age - timedelta(hours=1))
    return a, b


def test_hook_test_names_a_winner_or_a_draw(db: Session) -> None:
    _history(db)
    a, _ = _ab(db, 3000, 1000, timedelta(days=10))
    tests = winners.hook_tests(winners.scored_posts(db))
    test = next(t for t in tests if t.clip_id == a.clip_id)
    assert test.winner is not None and test.winner.variant_id == a.id
    assert [e.label for e in test.entries] == ["A", "B"]
    table = {x.hook_type: x for x in winners.balance(tests)}
    assert table["question"].wins == 1 and table["countdown"].losses == 1

    c, _ = _ab(db, 1100, 1000, timedelta(days=9))
    tests = winners.hook_tests(winners.scored_posts(db))
    draw = next(t for t in tests if t.clip_id == c.clip_id)
    assert draw.winner is None  # 10 % better is not a win
    assert winners.next_hook("question", "surprise", winners.balance(tests)) != "question"


def test_winner_gets_new_hook_and_part_two_idea_once(db: Session) -> None:
    _history(db)
    a, _ = _ab(db, 3000, 1000, timedelta(days=10))
    fresh_chain = build_chain(db)  # a winner too young to recycle
    fresh_chain.variant.title = "Ganz neu"
    _post(db, fresh_chain.variant, 5000, timedelta(days=2))

    res = winners.run(db)
    by_variant = {r["variant_id"]: r for r in res["recycled"]}
    assert a.id in by_variant and fresh_chain.variant.id not in by_variant
    r = by_variant[a.id]
    new = db.get(Variant, r["recycled_variant_id"])
    assert new is not None
    assert new.status == VideoStatus.EDITING and new.variant_label == "R1"
    assert new.clip_id == a.clip_id and new.channel_id == a.channel_id
    assert new.hook_type != a.hook_type and new.concept["recycle_of"] == a.id
    assert new.storage_uri == "local://clips/c.mp4"
    idea = db.get(Idea, r["idea_id"])
    assert idea is not None and idea.title == "Teil 2: Clutch in Runde 13"
    assert f"[winner:{r['post_id']}]" in idea.reasoning
    assert db.scalar(select(Notification).where(Notification.kind == "winner")) is not None

    again = winners.run(db)
    assert again["recycled"] == []
    assert len(db.scalars(select(Variant).where(Variant.concept["recycle_of"].as_integer()
                                                == a.id)).all()) == 1  # fmt: skip


def test_agent_skips_without_posts_and_runs_with_them(db: Session) -> None:
    settings = get_settings()
    skipped = orchestrator.run_agent(db, settings, "winner_recycling", {"sweep": True})
    assert skipped.status == AgentRunStatus.SKIPPED
    _history(db)
    _ab(db, 3000, 1000, timedelta(days=10))
    done = orchestrator.run_agent(db, settings, "winner_recycling", {"sweep": True})
    assert done.status == AgentRunStatus.SUCCEEDED, done.error


def test_api_hook_report(api: TestClient, db: Session, make_user: Callable[..., User]) -> None:
    make_user(email="viewer@example.com", role=UserRole.VIEWER)
    login(api, "viewer@example.com")
    _history(db)
    a, _ = _ab(db, 3000, 1000, timedelta(days=10))
    winners.run(db)
    data = api.get("/api/analytics/hooks").json()
    test = next(t for t in data["tests"] if t["clip_id"] == a.clip_id)
    assert test["winner_hook"] == "question"
    assert any(b["hook_type"] == "question" and b["wins"] == 1 for b in data["balance"])
    win = next(w for w in data["winners"] if w["variant_id"] == a.id)
    assert win["recycled_variant_id"] is not None and win["new_hook"] != "question"
    assert data["winner_score"] == winners.WINNER_SCORE
