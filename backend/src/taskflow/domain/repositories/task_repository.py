"""Task repository port, plus the query objects it accepts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from taskflow.domain.entities.task import Task
from taskflow.domain.enums import TaskPriority, TaskStatus
from taskflow.domain.repositories.pagination import Page, Pagination


class TaskSortField(StrEnum):
    DUE_DATE = "due_date"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    PRIORITY = "priority"
    TITLE = "title"
    STATUS = "status"


class SortDirection(StrEnum):
    ASC = "asc"
    DESC = "desc"


@dataclass(frozen=True, slots=True)
class TaskSorting:
    field: TaskSortField = TaskSortField.CREATED_AT
    direction: SortDirection = SortDirection.DESC


@dataclass(frozen=True, slots=True)
class TaskFilter:
    """A declarative description of *which* tasks to return.

    Modelled as a value object rather than a pile of keyword arguments so the
    same criteria can be passed to the SQL adapter, to an in-memory fake in
    tests, and to the Celery job that scans for overdue work.

    ``visible_to`` is the security-relevant field: it restricts results to
    tasks the actor owns *or* is assigned to. Every list query in the
    application layer sets it, which makes accidental data leaks a matter of
    one obvious missing argument rather than a forgotten ``WHERE`` clause
    somewhere in a hand-written query.
    """

    visible_to: UUID | None = None
    owner_id: UUID | None = None
    assignee_id: UUID | None = None
    unassigned_only: bool = False
    statuses: tuple[TaskStatus, ...] = ()
    priorities: tuple[TaskPriority, ...] = ()
    due_before: datetime | None = None
    due_after: datetime | None = None
    has_due_date: bool | None = None
    is_overdue_at: datetime | None = None
    search: str | None = None


class TaskRepository(Protocol):
    """Persistence port for the :class:`Task` aggregate."""

    async def add(self, task: Task) -> None:
        """Stage a new task for insertion."""
        ...

    async def get(self, task_id: UUID) -> Task | None:
        """Load a task by id, or ``None`` when it does not exist."""
        ...

    async def update(self, task: Task) -> None:
        """Persist the mutated state of an existing task."""
        ...

    async def delete(self, task_id: UUID) -> bool:
        """Remove a task. Returns ``False`` when there was nothing to remove."""
        ...

    async def find(
        self,
        filters: TaskFilter,
        pagination: Pagination,
        sorting: TaskSorting | None = None,
    ) -> Page[Task]:
        """Return a page of tasks matching ``filters``."""
        ...

    async def count(self, filters: TaskFilter) -> int:
        """Return how many tasks match ``filters``."""
        ...
