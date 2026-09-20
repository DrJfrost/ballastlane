"""Enumerations that are part of the business vocabulary."""

from __future__ import annotations

from enum import StrEnum


class TaskStatus(StrEnum):
    """Lifecycle of a task.

    The allowed transitions are encoded in :attr:`TRANSITIONS` and enforced by
    :class:`taskflow.domain.entities.task.Task`, not by the API layer.
    """

    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"

    @property
    def is_open(self) -> bool:
        return self in _OPEN_STATUSES

    @property
    def is_closed(self) -> bool:
        return not self.is_open


_OPEN_STATUSES = frozenset({TaskStatus.TODO, TaskStatus.IN_PROGRESS})

#: Directed graph of legal status transitions.
TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.TODO: frozenset({TaskStatus.IN_PROGRESS, TaskStatus.DONE, TaskStatus.CANCELLED}),
    TaskStatus.IN_PROGRESS: frozenset({TaskStatus.TODO, TaskStatus.DONE, TaskStatus.CANCELLED}),
    TaskStatus.DONE: frozenset({TaskStatus.TODO, TaskStatus.IN_PROGRESS}),
    TaskStatus.CANCELLED: frozenset({TaskStatus.TODO}),
}


class TaskPriority(StrEnum):
    """Business priority. Ordered via :attr:`weight` for sorting."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"

    @property
    def weight(self) -> int:
        return _PRIORITY_WEIGHTS[self]


_PRIORITY_WEIGHTS: dict[TaskPriority, int] = {
    TaskPriority.LOW: 0,
    TaskPriority.MEDIUM: 1,
    TaskPriority.HIGH: 2,
    TaskPriority.URGENT: 3,
}
