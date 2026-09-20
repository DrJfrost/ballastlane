"""Outbound DTOs (read models).

Use cases return these, never entities. Two reasons:

* an entity is mutable and carries behaviour that callers should not reach
  through the API boundary;
* the read model can denormalise (e.g. embed the assignee's name) and add
  derived fields (``is_overdue``) without polluting the aggregate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from taskflow.domain.entities import Task, User
from taskflow.domain.enums import TaskPriority, TaskStatus


@dataclass(frozen=True, slots=True)
class UserSummaryView:
    id: UUID
    email: str
    full_name: str
    initials: str

    @classmethod
    def from_entity(cls, user: User) -> UserSummaryView:
        return cls(
            id=user.id,
            email=user.email.value,
            full_name=user.full_name.value,
            initials=user.full_name.initials,
        )


@dataclass(frozen=True, slots=True)
class UserView:
    id: UUID
    email: str
    full_name: str
    initials: str
    is_active: bool
    created_at: datetime

    @classmethod
    def from_entity(cls, user: User) -> UserView:
        return cls(
            id=user.id,
            email=user.email.value,
            full_name=user.full_name.value,
            initials=user.full_name.initials,
            is_active=user.is_active,
            created_at=user.created_at,
        )


@dataclass(frozen=True, slots=True)
class TaskView:
    id: UUID
    title: str
    description: str
    status: TaskStatus
    priority: TaskPriority
    due_date: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    owner: UserSummaryView | None
    assignee: UserSummaryView | None
    is_overdue: bool
    days_until_due: int | None
    can_edit: bool
    can_change_status: bool

    @classmethod
    def from_entity(
        cls,
        task: Task,
        *,
        now: datetime,
        actor_id: UUID,
        owner: User | None = None,
        assignee: User | None = None,
    ) -> TaskView:
        """Build the read model.

        ``can_edit`` / ``can_change_status`` are projected from the same
        entity predicates the write path enforces. Sending them to the client
        lets the UI disable buttons it is not allowed to use, without the
        frontend re-implementing (and drifting from) the permission rules.
        """
        return cls(
            id=task.id,
            title=task.title.value,
            description=task.description.value,
            status=task.status,
            priority=task.priority,
            due_date=task.due_date,
            completed_at=task.completed_at,
            created_at=task.created_at,
            updated_at=task.updated_at,
            owner=UserSummaryView.from_entity(owner) if owner else None,
            assignee=UserSummaryView.from_entity(assignee) if assignee else None,
            is_overdue=task.is_overdue(now),
            days_until_due=task.days_until_due(now),
            can_edit=task.is_managed_by(actor_id),
            can_change_status=task.can_change_status(actor_id),
        )


@dataclass(frozen=True, slots=True)
class TokenPairView:
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


@dataclass(frozen=True, slots=True)
class AuthenticatedUserView:
    """What the auth dependency hands to routers: identity, never credentials.

    Note what is *absent*: ``hashed_password``. The routers physically cannot
    leak it, because they never receive it.
    """

    id: UUID
    email: str
    full_name: str
    initials: str
    is_active: bool
    created_at: datetime

    @classmethod
    def from_entity(cls, user: User) -> AuthenticatedUserView:
        return cls(
            id=user.id,
            email=user.email.value,
            full_name=user.full_name.value,
            initials=user.full_name.initials,
            is_active=user.is_active,
            created_at=user.created_at,
        )


@dataclass(frozen=True, slots=True)
class TaskStatsView:
    """Counters for the dashboard header."""

    total: int
    todo: int
    in_progress: int
    done: int
    cancelled: int
    overdue: int
    assigned_to_me: int
