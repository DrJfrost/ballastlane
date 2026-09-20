"""Task aggregate: the heart of the domain.

Every rule about what a task *is* and how it may change lives here, so it can
be unit-tested without a database, an HTTP client or an event loop. The API
layer only translates JSON into calls on these methods.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from taskflow.domain.entities.base import AggregateRoot
from taskflow.domain.entities.user import User
from taskflow.domain.enums import TRANSITIONS, TaskPriority, TaskStatus
from taskflow.domain.errors import ConflictError, ValidationError
from taskflow.domain.events import (
    TaskAssigned,
    TaskCompleted,
    TaskDueDateChanged,
    TaskUnassigned,
)
from taskflow.domain.value_objects import TaskDescription, TaskTitle


@dataclass(eq=False, slots=True)
class Task(AggregateRoot):
    """A unit of work owned by one user and optionally assigned to another.

    Authorisation model (a business rule, hence it lives in the entity):

    * **owner** -- full control: edit, reschedule, assign, change status, delete.
    * **assignee** -- may move the task through its lifecycle (start / complete
      / reopen) but may not rewrite its content, reassign it or delete it.
    * **anybody else** -- the task is invisible; callers must translate that
      into a 404 rather than a 403, because a 403 would confirm the id exists
      and turn the endpoint into an existence oracle.
    """

    id: UUID
    title: TaskTitle
    description: TaskDescription
    status: TaskStatus
    priority: TaskPriority
    owner_id: UUID
    created_at: datetime
    updated_at: datetime
    assignee_id: UUID | None = None
    due_date: datetime | None = None
    completed_at: datetime | None = None

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #
    @classmethod
    def create(
        cls,
        *,
        title: TaskTitle,
        owner_id: UUID,
        now: datetime,
        description: TaskDescription | None = None,
        priority: TaskPriority = TaskPriority.MEDIUM,
        due_date: datetime | None = None,
        task_id: UUID | None = None,
    ) -> Task:
        """Factory for a new, open task.

        A due date in the past is rejected: accepting one would create a task
        that is born overdue, which is never what the caller intended. Tasks
        *without* a due date are perfectly valid.
        """
        _require_aware(due_date, field="due_date")
        if due_date is not None and due_date <= now:
            raise ValidationError(
                "Due date must be in the future.",
                details={"field": "due_date", "value": due_date.isoformat()},
            )
        return cls(
            id=task_id or uuid4(),
            title=title,
            description=description or TaskDescription(),
            status=TaskStatus.TODO,
            priority=priority,
            owner_id=owner_id,
            created_at=now,
            updated_at=now,
            assignee_id=None,
            due_date=due_date,
            completed_at=None,
        )

    # ------------------------------------------------------------------ #
    # Authorisation predicates
    # ------------------------------------------------------------------ #
    def is_visible_to(self, user_id: UUID) -> bool:
        return user_id in (self.owner_id, self.assignee_id)

    def is_managed_by(self, user_id: UUID) -> bool:
        """Only the owner may edit content, reassign or delete."""
        return user_id == self.owner_id

    def can_change_status(self, user_id: UUID) -> bool:
        """The owner *and* the assignee may drive the lifecycle."""
        return user_id in (self.owner_id, self.assignee_id)

    # ------------------------------------------------------------------ #
    # Content
    # ------------------------------------------------------------------ #
    def rename(self, title: TaskTitle, *, now: datetime) -> None:
        if title == self.title:
            return
        self._guard_mutable()
        self.title = title
        self._touch(now)

    def change_description(self, description: TaskDescription, *, now: datetime) -> None:
        if description == self.description:
            return
        self._guard_mutable()
        self.description = description
        self._touch(now)

    def change_priority(self, priority: TaskPriority, *, now: datetime) -> None:
        if priority == self.priority:
            return
        self._guard_mutable()
        self.priority = priority
        self._touch(now)

    def reschedule(self, due_date: datetime | None, *, actor_id: UUID, now: datetime) -> None:
        """Move (or clear) the deadline.

        Unlike :meth:`create`, a past date is refused only while the task is
        still open -- a closed task keeps whatever history it had.
        """
        _require_aware(due_date, field="due_date")
        if due_date == self.due_date:
            return
        self._guard_mutable()
        if due_date is not None and due_date <= now:
            raise ValidationError(
                "Due date must be in the future.",
                details={"field": "due_date", "value": due_date.isoformat()},
            )
        previous, self.due_date = self.due_date, due_date
        self._touch(now)
        self.record(
            TaskDueDateChanged(
                occurred_at=now,
                task_id=self.id,
                previous_due_date=previous,
                new_due_date=due_date,
                changed_by=actor_id,
            )
        )

    # ------------------------------------------------------------------ #
    # Assignment
    # ------------------------------------------------------------------ #
    def assign_to(self, assignee: User, *, actor_id: UUID, now: datetime) -> None:
        """Assign to an active user. Re-assigning to the same user is a no-op."""
        self._guard_mutable()
        if not assignee.can_be_assigned_work:
            raise ConflictError(
                "Cannot assign a task to a deactivated user.",
                details={"assignee_id": str(assignee.id)},
            )
        if self.assignee_id == assignee.id:
            return
        self.assignee_id = assignee.id
        self._touch(now)
        self.record(
            TaskAssigned(
                occurred_at=now,
                task_id=self.id,
                task_title=self.title.value,
                assignee_id=assignee.id,
                assigned_by=actor_id,
            )
        )

    def unassign(self, *, actor_id: UUID, now: datetime) -> None:
        if self.assignee_id is None:
            return
        self._guard_mutable()
        previous, self.assignee_id = self.assignee_id, None
        self._touch(now)
        self.record(
            TaskUnassigned(
                occurred_at=now,
                task_id=self.id,
                previous_assignee_id=previous,
                unassigned_by=actor_id,
            )
        )

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def change_status(self, status: TaskStatus, *, actor_id: UUID, now: datetime) -> None:
        """Single entry point for lifecycle moves, validated against TRANSITIONS."""
        if status == self.status:
            return
        if status not in TRANSITIONS[self.status]:
            raise ConflictError(
                f"Cannot move a task from '{self.status}' to '{status}'.",
                details={"from": self.status.value, "to": status.value},
            )
        if status is TaskStatus.DONE:
            self._complete(actor_id=actor_id, now=now)
            return
        self.status = status
        self.completed_at = None
        self._touch(now)

    def start(self, *, actor_id: UUID, now: datetime) -> None:
        self.change_status(TaskStatus.IN_PROGRESS, actor_id=actor_id, now=now)

    def complete(self, *, actor_id: UUID, now: datetime) -> None:
        if self.status is TaskStatus.DONE:
            raise ConflictError("Task is already completed.", details={"task_id": str(self.id)})
        self.change_status(TaskStatus.DONE, actor_id=actor_id, now=now)

    def reopen(self, *, actor_id: UUID, now: datetime) -> None:
        if self.status.is_open:
            raise ConflictError(
                "Only a closed task can be reopened.",
                details={"task_id": str(self.id), "status": self.status.value},
            )
        self.change_status(TaskStatus.TODO, actor_id=actor_id, now=now)

    def cancel(self, *, actor_id: UUID, now: datetime) -> None:
        self.change_status(TaskStatus.CANCELLED, actor_id=actor_id, now=now)

    def _complete(self, *, actor_id: UUID, now: datetime) -> None:
        was_overdue = self.is_overdue(now)
        self.status = TaskStatus.DONE
        self.completed_at = now
        self._touch(now)
        self.record(
            TaskCompleted(
                occurred_at=now,
                task_id=self.id,
                task_title=self.title.value,
                completed_by=actor_id,
                owner_id=self.owner_id,
                was_overdue=was_overdue,
            )
        )

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #
    def is_overdue(self, now: datetime) -> bool:
        """A task is overdue when it is still open and its deadline has passed."""
        return self.due_date is not None and self.status.is_open and self.due_date < now

    def days_until_due(self, now: datetime) -> int | None:
        if self.due_date is None:
            return None
        return (self.due_date - now).days

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _guard_mutable(self) -> None:
        """Content of a cancelled task is frozen; reopen it first."""
        if self.status is TaskStatus.CANCELLED:
            raise ConflictError(
                "A cancelled task cannot be modified; reopen it first.",
                details={"task_id": str(self.id)},
            )

    def _touch(self, now: datetime) -> None:
        self.updated_at = now

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Task) and other.id == self.id

    def __hash__(self) -> int:
        return hash(("Task", self.id))


def _require_aware(value: datetime | None, *, field: str) -> None:
    """Reject naive datetimes at the domain boundary.

    Mixing naive and aware datetimes is a classic source of silent bugs in
    scheduling code: comparisons raise ``TypeError`` at runtime, and storage
    round-trips shift by the local offset of whichever machine wrote the row.
    The domain therefore only speaks timezone-aware UTC.
    """
    if value is not None and value.tzinfo is None:
        raise ValidationError(
            f"Field '{field}' must be timezone-aware.", details={"field": field}
        )
