"""Allowed status transitions for material and video variants.

The tables below are the single source of truth for the workflow
(PROJECT_SPEC section 16, docs/ARCHITECTURE.md section 4). Every status change
in the system must go through :func:`assert_transition`.

``FAILED`` can be entered from every non-terminal status. Leaving ``FAILED``
is only possible back to the status in which the error happened (retry), which
the workflow service enforces using the stored ``last_good_status``.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from core.enums import MaterialStatus as M
from core.enums import VideoStatus as V

MATERIAL_TRANSITIONS: Mapping[M, frozenset[M]] = {
    M.DISCOVERED: frozenset({M.RIGHTS_PENDING}),
    M.RIGHTS_PENDING: frozenset({M.RIGHTS_APPROVED, M.RIGHTS_REJECTED}),
    M.RIGHTS_APPROVED: frozenset({M.ANALYZED, M.RIGHTS_PENDING}),  # re-check, e.g. expiry
    M.RIGHTS_REJECTED: frozenset({M.RIGHTS_PENDING}),  # new license evidence
    M.ANALYZED: frozenset({M.RIGHTS_PENDING}),  # license expired -> re-check
    M.FAILED: frozenset(),  # handled via retry
}

VIDEO_TRANSITIONS: Mapping[V, frozenset[V]] = {
    V.SCENE_SELECTED: frozenset({V.EDITING, V.ARCHIVED}),
    V.EDITING: frozenset({V.LOCALIZATION, V.ARCHIVED}),
    V.LOCALIZATION: frozenset({V.VOICEOVER, V.ARCHIVED}),
    V.VOICEOVER: frozenset({V.SUBTITLES, V.ARCHIVED}),
    V.SUBTITLES: frozenset({V.QUALITY_CHECK, V.ARCHIVED}),
    V.QUALITY_CHECK: frozenset({V.QUALITY_APPROVED, V.QUALITY_REJECTED}),
    V.QUALITY_APPROVED: frozenset({V.READY_TO_PUBLISH, V.ARCHIVED}),
    V.QUALITY_REJECTED: frozenset({V.EDITING, V.ARCHIVED}),
    # QUALITY_APPROVED: an approval in the approval center is withdrawn (extension E8)
    V.READY_TO_PUBLISH: frozenset({V.SCHEDULED, V.QUALITY_CHECK, V.QUALITY_APPROVED, V.ARCHIVED}),
    V.SCHEDULED: frozenset({V.PUBLISHED, V.READY_TO_PUBLISH}),  # unschedule
    V.PUBLISHED: frozenset({V.ANALYTICS_PENDING}),
    V.ANALYTICS_PENDING: frozenset({V.ANALYZED}),
    V.ANALYZED: frozenset({V.ANALYTICS_PENDING, V.ARCHIVED}),  # new window measured
    V.ARCHIVED: frozenset(),
    V.FAILED: frozenset(),  # handled via retry
}

MATERIAL_TERMINAL: frozenset[M] = frozenset()
VIDEO_TERMINAL: frozenset[V] = frozenset({V.ARCHIVED})


class InvalidTransitionError(ValueError):
    """Raised when a status change is not allowed by the workflow tables."""

    def __init__(self, current: StrEnum, target: StrEnum) -> None:
        super().__init__(f"Transition {current.value} -> {target.value} is not allowed")
        self.current = current
        self.target = target


def _table_for(status: StrEnum) -> tuple[Mapping[StrEnum, frozenset[StrEnum]], frozenset[StrEnum]]:
    if isinstance(status, M):
        return MATERIAL_TRANSITIONS, MATERIAL_TERMINAL  # type: ignore[return-value]
    if isinstance(status, V):
        return VIDEO_TRANSITIONS, VIDEO_TERMINAL  # type: ignore[return-value]
    raise TypeError(f"Unknown status type: {type(status).__name__}")


def can_transition(current: StrEnum, target: StrEnum) -> bool:
    """Return True if ``current -> target`` is allowed (excluding retry from FAILED)."""
    if type(current) is not type(target):
        return False
    table, terminal = _table_for(current)
    if target.value == "FAILED":
        return current.value != "FAILED" and current not in terminal
    return target in table[current]


def assert_transition(current: StrEnum, target: StrEnum) -> None:
    """Raise :class:`InvalidTransitionError` unless the transition is allowed."""
    if not can_transition(current, target):
        raise InvalidTransitionError(current, target)
