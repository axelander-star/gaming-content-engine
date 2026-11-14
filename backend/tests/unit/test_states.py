from __future__ import annotations

import itertools

import pytest

from core.enums import MaterialStatus as M
from core.enums import VideoStatus as V
from core.states import (
    MATERIAL_TRANSITIONS,
    VIDEO_TRANSITIONS,
    InvalidTransitionError,
    assert_transition,
    can_transition,
)

HAPPY_VIDEO_PATH = [
    V.SCENE_SELECTED,
    V.EDITING,
    V.LOCALIZATION,
    V.VOICEOVER,
    V.SUBTITLES,
    V.QUALITY_CHECK,
    V.QUALITY_APPROVED,
    V.READY_TO_PUBLISH,
    V.SCHEDULED,
    V.PUBLISHED,
    V.ANALYTICS_PENDING,
    V.ANALYZED,
    V.ARCHIVED,
]


def test_every_status_has_a_transition_entry() -> None:
    assert set(MATERIAL_TRANSITIONS) == set(M)
    assert set(VIDEO_TRANSITIONS) == set(V)


def test_spec_video_order_is_a_valid_path() -> None:
    for current, nxt in itertools.pairwise(HAPPY_VIDEO_PATH):
        assert can_transition(current, nxt), f"{current} -> {nxt}"


def test_material_happy_path() -> None:
    path = [M.DISCOVERED, M.RIGHTS_PENDING, M.RIGHTS_APPROVED, M.ANALYZED]
    for current, nxt in itertools.pairwise(path):
        assert can_transition(current, nxt)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (M.DISCOVERED, M.ANALYZED),  # rights check cannot be skipped
        (M.RIGHTS_PENDING, M.ANALYZED),
        (M.RIGHTS_REJECTED, M.RIGHTS_APPROVED),  # must be re-checked
    ],
)
def test_rights_cannot_be_skipped(current: M, target: M) -> None:
    assert not can_transition(current, target)


@pytest.mark.parametrize(
    "current",
    [V.EDITING, V.SUBTITLES, V.QUALITY_CHECK, V.QUALITY_REJECTED, V.SCENE_SELECTED],
)
def test_no_publication_without_quality_approval(current: V) -> None:
    assert not can_transition(current, V.READY_TO_PUBLISH)
    assert not can_transition(current, V.SCHEDULED)
    assert not can_transition(current, V.PUBLISHED)


def test_publish_only_from_scheduled() -> None:
    allowed = [s for s in V if can_transition(s, V.PUBLISHED)]
    assert allowed == [V.SCHEDULED]


def test_failed_reachable_from_non_terminal_only() -> None:
    assert can_transition(V.EDITING, V.FAILED)
    assert can_transition(M.RIGHTS_PENDING, M.FAILED)
    assert not can_transition(V.ARCHIVED, V.FAILED)
    assert not can_transition(V.FAILED, V.FAILED)


def test_cross_type_transition_rejected() -> None:
    assert not can_transition(M.ANALYZED, V.ARCHIVED)


def test_assert_transition_raises() -> None:
    with pytest.raises(InvalidTransitionError, match="EDITING -> PUBLISHED"):
        assert_transition(V.EDITING, V.PUBLISHED)
