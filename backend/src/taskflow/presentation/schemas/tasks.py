"""Task request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from taskflow.application.dto import (
    UNSET,
    CreateTaskCommand,
    Maybe,
    TaskStatsView,
    TaskView,
    UpdateTaskCommand,
)
from taskflow.application.dto.views import UserSummaryView
from taskflow.domain.enums import TaskPriority, TaskStatus
from taskflow.presentation.schemas.auth import UserSummaryResponse
from taskflow.presentation.schemas.fields import STRICT_BODY, UtcDateTime


class CreateTaskRequest(BaseModel):
    model_config = STRICT_BODY | ConfigDict(
        json_schema_extra={
            "example": {
                "title": "Draft the Q4 architecture review",
                "description": "Focus on the ingestion pipeline.",
                "priority": "high",
                "due_date": "2026-12-01T17:00:00Z",
                "assignee_id": None,
            }
        }
    )

    title: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=5000)
    priority: TaskPriority = TaskPriority.MEDIUM
    due_date: UtcDateTime | None = None
    assignee_id: UUID | None = None

    def to_command(self, actor_id: UUID) -> CreateTaskCommand:
        return CreateTaskCommand(
            actor_id=actor_id,
            title=self.title,
            description=self.description,
            priority=self.priority,
            due_date=self.due_date,
            assignee_id=self.assignee_id,
        )


class UpdateTaskRequest(BaseModel):
    """PATCH payload.

    Every field is optional *and* nullable, so the schema alone cannot tell
    "omitted" from "explicitly null". ``model_fields_set`` -- what Pydantic
    records as actually present in the JSON -- is what makes the difference,
    and it is mapped onto the application's ``UNSET`` sentinel below.
    """

    model_config = STRICT_BODY | ConfigDict(
        json_schema_extra={"example": {"status": "in_progress", "priority": "urgent"}}
    )

    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    priority: TaskPriority | None = None
    status: TaskStatus | None = None
    due_date: UtcDateTime | None = None
    assignee_id: UUID | None = None

    @model_validator(mode="after")
    def _reject_empty_patch(self) -> UpdateTaskRequest:
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update.")
        return self

    @model_validator(mode="after")
    def _reject_null_where_not_nullable(self) -> UpdateTaskRequest:
        """Only ``due_date`` and ``assignee_id`` may legitimately be null.

        A ``{"title": null}`` is a client bug, and answering 422 is far more
        helpful than quietly ignoring the field (which is what a plain
        ``if value is not None`` in the use case would do).
        """
        for name in ("title", "description", "priority", "status"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"Field '{name}' cannot be null.")
        return self

    def to_command(self, actor_id: UUID, task_id: UUID) -> UpdateTaskCommand:
        def nullable[T](name: str, value: T | None) -> Maybe[T | None]:
            """For fields where ``null`` is a meaningful instruction."""
            return value if name in self.model_fields_set else UNSET

        def required[T](name: str, value: T | None) -> Maybe[T]:
            """For fields that cannot be null once present.

            ``_reject_null_where_not_nullable`` has already turned an
            explicit ``null`` into a 422, so inside this branch the value is
            known to be set. The cast makes that guarantee visible to the
            type checker instead of leaving a ``T | None`` to leak into the
            command.
            """
            if name not in self.model_fields_set:
                return UNSET
            return cast("T", value)

        return UpdateTaskCommand(
            actor_id=actor_id,
            task_id=task_id,
            title=required("title", self.title),
            description=required("description", self.description),
            priority=required("priority", self.priority),
            status=required("status", self.status),
            due_date=nullable("due_date", self.due_date),
            assignee_id=nullable("assignee_id", self.assignee_id),
        )


class AssignTaskRequest(BaseModel):
    model_config = STRICT_BODY | ConfigDict(
        json_schema_extra={"example": {"assignee_id": "0f3f0a4a-0000-4000-8000-000000000002"}}
    )

    assignee_id: UUID | None = Field(
        default=None, description="Pass null to unassign the task."
    )


class TaskResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    title: str
    description: str
    status: TaskStatus
    priority: TaskPriority
    due_date: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    owner: UserSummaryResponse | None
    assignee: UserSummaryResponse | None
    is_overdue: bool
    days_until_due: int | None
    can_edit: bool
    can_change_status: bool

    @classmethod
    def from_view(cls, view: TaskView) -> TaskResponse:
        return cls(
            id=view.id,
            title=view.title,
            description=view.description,
            status=view.status,
            priority=view.priority,
            due_date=view.due_date,
            completed_at=view.completed_at,
            created_at=view.created_at,
            updated_at=view.updated_at,
            owner=_person(view.owner),
            assignee=_person(view.assignee),
            is_overdue=view.is_overdue,
            days_until_due=view.days_until_due,
            can_edit=view.can_edit,
            can_change_status=view.can_change_status,
        )


class TaskStatsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int
    todo: int
    in_progress: int
    done: int
    cancelled: int
    overdue: int
    assigned_to_me: int

    @classmethod
    def from_view(cls, view: TaskStatsView) -> TaskStatsResponse:
        return cls(
            total=view.total,
            todo=view.todo,
            in_progress=view.in_progress,
            done=view.done,
            cancelled=view.cancelled,
            overdue=view.overdue,
            assigned_to_me=view.assigned_to_me,
        )


def _person(view: UserSummaryView | None) -> UserSummaryResponse | None:
    if view is None:
        return None
    return UserSummaryResponse(
        id=view.id,
        email=view.email,
        full_name=view.full_name,
        initials=view.initials,
    )
