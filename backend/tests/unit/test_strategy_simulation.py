"""Phase 11: publishing amount, selection and timing on synthetic channel histories."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from core.enums import MetricWindow
from services import strategy
from services.strategy import Bounds, Candidate, PostPerf, Supply

W = MetricWindow
START = datetime(2026, 10, 1, 16, 0, tzinfo=UTC)
PLENTY = Supply(ready=10, approved_per_day=4.0, quality_recent=0.85, quality_before=0.85)
BOUNDS = Bounds(min_posts=0, max_posts=6, interval_minutes=60)


def history(
    views: Sequence[float], *, windows: tuple[MetricWindow, ...] = (W.H24, W.H48)
) -> list[PostPerf]:
    """One post per day with the given views (engagement and retention typical)."""
    posts = []
    for i, v in enumerate(views):
        values = {"views": v, "likes": v * 0.05, "comments": v * 0.005, "retention": 60.0}
        posts.append(
            PostPerf(
                post_id=i + 1,
                published_at=START + timedelta(days=i),
                windows={w: dict(values) for w in windows},
            )
        )
    return posts


def decide(views: Sequence[float], previous: int | None = 2, **kw: object) -> strategy.Decision:
    supply = kw.pop("supply", PLENTY)
    bounds = kw.pop("bounds", BOUNDS)
    assert not kw
    return strategy.decide_amount(previous, strategy.assess(history(views)), supply, bounds)  # type: ignore[arg-type]


# --- assessment -------------------------------------------------------------------


def test_posts_are_compared_with_their_own_window_and_earlier_posts_only() -> None:
    a = strategy.assess(history([1000] * 5 + [2000]))
    assert len(a.judged) == 1  # the first five build the baseline
    assert a.judged[0].window == W.H48 and a.judged[0].parts["views"] == 2.0
    assert a.baselines["48h"]["views"] == 1000.0


def test_young_posts_are_not_judged() -> None:
    posts = [
        *history([1000] * 8),
        PostPerf(99, START + timedelta(days=9), {W.H1: {"views": 5.0}, W.H6: {"views": 40.0}}),
    ]
    a = strategy.assess(posts)
    assert a.waiting == 1 and 99 not in {j.post_id for j in a.judged}


def test_one_viral_post_is_capped() -> None:
    a = strategy.assess(history([1000] * 6 + [10_000_000]))
    assert a.judged[-1].parts["views"] == strategy.REL_CAP


# --- amount: scenarios from the acceptance criteria -------------------------------


def test_too_little_data_keeps_the_amount() -> None:
    d = decide([1000, 3000, 5000], previous=2)
    assert d.posts_per_day == 2 and d.change == 0
    assert "Zu wenig ausgewertete Videos" in d.reasons[0]


def test_first_strategy_starts_cautiously() -> None:
    d = decide([], previous=None)
    assert d.posts_per_day == 1 and "vorsichtiger Start" in d.reasons[0]
    d = decide([], previous=None, bounds=Bounds(2, 6, 60))
    assert d.posts_per_day == 2


def test_single_viral_video_does_not_raise_the_amount() -> None:
    d = decide([1000] * 10 + [1000, 950, 1050, 980, 1020, 90_000], previous=2)
    assert d.posts_per_day == 2
    assert any("Ausreißer" in r for r in d.reasons)


def test_broad_success_raises_by_one_step() -> None:
    d = decide([1000] * 10 + [1500, 1400, 1600, 1550, 1450, 1700], previous=2)
    assert d.posts_per_day == 3 and d.change == 1


def test_weak_results_lower_the_amount_but_not_below_minimum() -> None:
    assert decide([1000] * 10 + [600] * 6, previous=3).posts_per_day == 2
    assert decide([1000] * 10 + [600] * 6, previous=1, bounds=Bounds(1, 6, 60)).posts_per_day == 1


def test_quality_drop_lowers_the_amount_even_with_good_results() -> None:
    supply = Supply(ready=10, approved_per_day=4, quality_recent=0.72, quality_before=0.88)
    d = decide([1000] * 10 + [1500] * 6, previous=3, supply=supply)
    assert d.posts_per_day == 2
    assert any("Qualität gesunken" in r for r in d.reasons)


def test_increase_waits_until_the_new_amount_is_measured() -> None:
    views = [1000] * 10 + [1500] * 6
    a = strategy.assess(history(views))
    held = strategy.decide_amount(2, a, PLENTY, BOUNDS, days_since_change=1)
    assert held.posts_per_day == 2 and any("erst messen" in r for r in held.reasons)
    assert strategy.decide_amount(2, a, PLENTY, BOUNDS, days_since_change=3).posts_per_day == 3
    weak = strategy.assess(history([1000] * 10 + [600] * 6))
    assert strategy.decide_amount(3, weak, PLENTY, BOUNDS, days_since_change=1).posts_per_day == 2


def test_no_increase_without_videos_to_post() -> None:
    supply = Supply(ready=1, approved_per_day=0.5, quality_recent=None, quality_before=None)
    d = decide([1000] * 10 + [1500] * 6, previous=2, supply=supply)
    assert d.posts_per_day == 2 and any("bereit" in r for r in d.reasons)


@pytest.mark.parametrize(
    ("bounds", "expected"),
    [
        (Bounds(0, 0, 60), 0),  # not configured
        (Bounds(0, 6, 60, paused=True), 0),
        (Bounds(0, 2, 60), 2),  # max bound
        (Bounds(0, 10, 300, window=(11, 21)), 3),  # interval: 11:00, 16:00, 21:00
    ],
)
def test_bounds_always_win(bounds: Bounds, expected: int) -> None:
    d = decide([1000] * 10 + [1500] * 6, previous=4, bounds=bounds)
    assert d.posts_per_day == expected


def test_multi_day_simulation_is_damped_and_bounded() -> None:
    """A channel that grows steadily, has one viral day and then loses quality."""
    bounds = Bounds(min_posts=1, max_posts=5, interval_minutes=90)
    views: list[float] = [1000] * 8
    amount: int | None = None
    amounts: list[int] = []
    changed: int | None = None
    for day in range(30):
        quality = (0.86, 0.86) if day < 22 else (0.70, 0.86)
        supply = Supply(
            ready=6, approved_per_day=3, quality_recent=quality[0], quality_before=quality[1]
        )
        since = None if changed is None else day - changed
        d = strategy.decide_amount(amount, strategy.assess(history(views)), supply, bounds, since)
        if amount is not None and d.posts_per_day != amount:
            changed = day
        if amount is not None:
            assert abs(d.posts_per_day - amount) <= strategy.MAX_STEP
        assert bounds.min_posts <= d.posts_per_day <= bounds.max_posts
        amount = d.posts_per_day
        amounts.append(amount)
        if day == 3:
            views.append(250_000)  # one viral video
        elif day < 12:
            views.append(1000)
        elif day < 22:
            views.append(1000 * (1.3 + 0.02 * (day - 12)))  # steady growth
        else:
            views.append(1000)
    assert amounts[0] == 1
    assert max(amounts[:12]) == 1  # the viral day did not raise the amount
    assert max(amounts) <= 5 and amounts[21] > amounts[11]  # growth raised it step by step
    assert amounts[-1] < amounts[21]  # quality drop lowered it again


# --- selection and timing ---------------------------------------------------------


def cand(vid: int, clip: int, q: float, **kw: object) -> Candidate:
    return Candidate(vid, clip, q, START + timedelta(minutes=vid), **kw)  # type: ignore[arg-type]


def test_choose_one_per_clip_and_keep_a_test_slot() -> None:
    cands = [
        cand(1, 10, 0.95),
        cand(2, 10, 0.94),  # sibling of 1
        cand(3, 11, 0.90),
        cand(4, 12, 0.80, experiment=True),
    ]
    chosen = strategy.choose(cands, 2, {})
    assert [c.variant_id for c in chosen] == [1, 4]
    assert [c.variant_id for c in strategy.choose(cands, 1, {})] == [1]


def test_proven_formats_are_preferred() -> None:
    groups = {"format": {"epic_scene": 1.8, "storytelling": 0.6}, "game": {}, "hook": {}}
    a = cand(1, 1, 0.85, video_format="storytelling")
    b = cand(2, 2, 0.80, video_format="epic_scene")
    assert [c.variant_id for c in strategy.choose([a, b], 1, groups)] == [2]


def test_group_scores_need_enough_posts() -> None:
    posts = [
        PostPerf(p.post_id, p.published_at, p.windows, video_format="pov" if i % 2 else "epic")
        for i, p in enumerate(history([1000] * 5 + [1500] * 6))
    ]
    groups = strategy.group_scores(posts, strategy.assess(posts))
    assert set(groups["format"]) == {"pov", "epic"}
    assert strategy.group_scores(posts[:7], strategy.assess(posts[:7]))["format"] == {}


def test_slot_times_respect_window_interval_now_and_taken() -> None:
    tz = ZoneInfo("Europe/Berlin")
    day = date(2026, 11, 16)
    now = datetime(2026, 11, 16, 7, 0, tzinfo=UTC)  # 08:00 local
    taken = [datetime(2026, 11, 16, 12, 0, tzinfo=tz)]
    times = strategy.slot_times(day, 3, Bounds(0, 5, 120), tz, now, taken)
    local = [t.astimezone(tz) for t in times]
    assert len(times) == 3 and local == sorted(local)
    assert all(11 <= t.hour <= 21 for t in local)
    for a in [*local, *taken]:
        for b in local:
            assert a == b or abs(a - b) >= timedelta(minutes=120)
    late = datetime(2026, 11, 16, 20, 30, tzinfo=UTC)  # 21:30 local: window over
    assert strategy.slot_times(day, 2, Bounds(0, 5, 60), tz, late, []) == []


def test_preferred_hours_come_first() -> None:
    tz = ZoneInfo("Europe/Berlin")
    now = datetime(2026, 11, 16, 6, 0, tzinfo=UTC)
    times = strategy.slot_times(date(2026, 11, 16), 1, Bounds(0, 5, 60), tz, now, [], [19, 12])
    assert times[0].astimezone(tz).hour == 19


def test_best_hours_from_history() -> None:
    tz = ZoneInfo("UTC")
    posts = []
    for i in range(12):
        hour = 18 if i % 2 else 9
        v = 1500 if hour == 18 else 900
        posts.append(
            PostPerf(i, START.replace(hour=hour) + timedelta(days=i), {W.H48: {"views": v}})
        )
    hours = strategy.best_hours(posts, strategy.assess(posts), tz)
    assert hours is not None and hours[0] == 18
    assert strategy.best_hours(posts[:3], strategy.assess(posts[:3]), tz) is None


def test_active_channel_never_drops_to_zero() -> None:
    weak = [1000] * 10 + [500] * 6
    assert decide(weak, previous=1).posts_per_day == 1  # min bound 0, still one a day
    restart = decide(weak, previous=0)
    assert restart.posts_per_day == 1 and any(
        "solange der Kanal aktiv" in r for r in restart.reasons
    )
