"""Domain events.

Aggregates record events instead of calling side-effecting services directly.
Use cases drain them after a successful commit and hand them to an
``EventPublisher`` port, whose production implementation enqueues Celery jobs.

This keeps two properties that matter:

* the domain stays free of infrastructure (no Celery import in the core);
* notifications are only emitted for transactions that actually committed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True, kw_only=True)
class DomainEvent:
    """Base class for anything an aggregate wants to announce."""

    occurred_at: datetime
    event_id: UUID = field(default_factory=uuid4)

    @property
    def name(self) -> str:
        return type(self).__name__


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskAssigned(DomainEvent):
    task_id: UUID
    task_title: str
    assignee_id: UUID
    assigned_by: UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskUnassigned(DomainEvent):
    task_id: UUID
    previous_assignee_id: UUID
    unassigned_by: UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskCompleted(DomainEvent):
    task_id: UUID
    task_title: str
    completed_by: UUID
    owner_id: UUID
    was_overdue: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskDueDateChanged(DomainEvent):
    task_id: UUID
    previous_due_date: datetime | None
    new_due_date: datetime | None
    changed_by: UUID
