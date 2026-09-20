"""Inbound DTOs (commands and queries).

Plain frozen dataclasses rather than Pydantic models: the application layer
must not depend on the web framework's validation library. Pydantic lives at
the edge (``presentation/schemas``) where it belongs -- parsing untrusted
JSON -- and the schemas convert themselves into these commands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from taskflow.application.dto.common import UNSET, Maybe
from taskflow.domain.enums import TaskPriority, TaskStatus
from taskflow.domain.repositories import (
    Pagination,
    SortDirection,
    TaskSortField,
)


# --------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class RegisterUserCommand:
    email: str
    full_name: str
    password: str


@dataclass(frozen=True, slots=True)
class LoginCommand:
    email: str
    password: str


@dataclass(frozen=True, slots=True)
class RefreshTokenCommand:
    refresh_token: str


# --------------------------------------------------------------------- #
# Tasks
# --------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class CreateTaskCommand:
    actor_id: UUID
    title: str
    description: str = ""
    priority: TaskPriority = TaskPriority.MEDIUM
    due_date: datetime | None = None
    assignee_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class UpdateTaskCommand:
    """Partial update. Every optional field defaults to :data:`UNSET`."""

    actor_id: UUID
    task_id: UUID
    title: Maybe[str] = UNSET
    description: Maybe[str] = UNSET
    priority: Maybe[TaskPriority] = UNSET
    status: Maybe[TaskStatus] = UNSET
    due_date: Maybe[datetime | None] = UNSET
    assignee_id: Maybe[UUID | None] = UNSET


@dataclass(frozen=True, slots=True)
class GetTaskQuery:
    actor_id: UUID
    task_id: UUID


@dataclass(frozen=True, slots=True)
class DeleteTaskCommand:
    actor_id: UUID
    task_id: UUID


@dataclass(frozen=True, slots=True)
class CompleteTaskCommand:
    actor_id: UUID
    task_id: UUID


@dataclass(frozen=True, slots=True)
class ReopenTaskCommand:
    actor_id: UUID
    task_id: UUID


@dataclass(frozen=True, slots=True)
class AssignTaskCommand:
    actor_id: UUID
    task_id: UUID
    assignee_id: UUID | None


@dataclass(frozen=True, slots=True)
class ListTasksQuery:
    """All list criteria in one object, including the actor doing the listing."""

    actor_id: UUID
    pagination: Pagination = field(default_factory=Pagination)
    statuses: tuple[TaskStatus, ...] = ()
    priorities: tuple[TaskPriority, ...] = ()
    due_before: datetime | None = None
    due_after: datetime | None = None
    has_due_date: bool | None = None
    overdue_only: bool = False
    assignee_id: UUID | None = None
    owner_id: UUID | None = None
    assigned_to_me: bool = False
    created_by_me: bool = False
    unassigned_only: bool = False
    search: str | None = None
    sort_by: TaskSortField = TaskSortField.CREATED_AT
    sort_dir: SortDirection = SortDirection.DESC


@dataclass(frozen=True, slots=True)
class TaskStatsQuery:
    actor_id: UUID


# --------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class ListUsersQuery:
    actor_id: UUID
    pagination: Pagination = field(default_factory=Pagination)
    search: str | None = None
    active_only: bool = True
