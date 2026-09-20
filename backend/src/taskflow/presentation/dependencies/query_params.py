"""Reusable query-parameter dependencies.

Declaring filters and pagination as dependencies rather than a dozen
arguments on the route function keeps the handler signature readable and puts
every default, bound and description in one documented place -- which is also
what Swagger renders.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Query

from taskflow.domain.enums import TaskPriority, TaskStatus
from taskflow.domain.repositories import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    Pagination,
    SortDirection,
    TaskSortField,
)
from taskflow.presentation.schemas.fields import as_utc


@dataclass(frozen=True, slots=True)
class PaginationParams:
    page: int
    page_size: int

    def to_pagination(self) -> Pagination:
        return Pagination(page=self.page, page_size=self.page_size)


def pagination_params(
    page: Annotated[int, Query(ge=1, description="1-based page number.")] = 1,
    page_size: Annotated[
        int,
        Query(
            ge=1,
            # The same ceiling the domain enforces, declared here so the
            # rejection happens at the edge with a clear field error and is
            # visible in the OpenAPI schema.
            le=MAX_PAGE_SIZE,
            description=f"Items per page (max {MAX_PAGE_SIZE}).",
        ),
    ] = DEFAULT_PAGE_SIZE,
) -> PaginationParams:
    return PaginationParams(page=page, page_size=page_size)


@dataclass(frozen=True, slots=True)
class TaskFilterParams:
    statuses: tuple[TaskStatus, ...]
    priorities: tuple[TaskPriority, ...]
    due_before: datetime | None
    due_after: datetime | None
    has_due_date: bool | None
    overdue_only: bool
    assignee_id: UUID | None
    owner_id: UUID | None
    assigned_to_me: bool
    created_by_me: bool
    unassigned_only: bool
    search: str | None
    sort_by: TaskSortField
    sort_dir: SortDirection


def task_filter_params(  # noqa: PLR0917 - FastAPI injects these by keyword
    status: Annotated[
        list[TaskStatus] | None,
        Query(
            description=(
                "Filter by status. Repeat the parameter to combine values, "
                "e.g. `?status=todo&status=in_progress`."
            )
        ),
    ] = None,
    priority: Annotated[
        list[TaskPriority] | None, Query(description="Filter by priority (repeatable).")
    ] = None,
    due_before: Annotated[
        datetime | None,
        Query(description="Only tasks due at or before this instant (ISO 8601)."),
    ] = None,
    due_after: Annotated[
        datetime | None,
        Query(description="Only tasks due at or after this instant (ISO 8601)."),
    ] = None,
    has_due_date: Annotated[
        bool | None, Query(description="`true` for dated tasks, `false` for undated.")
    ] = None,
    overdue_only: Annotated[
        bool, Query(description="Only open tasks whose deadline has passed.")
    ] = False,
    assignee_id: Annotated[UUID | None, Query(description="Filter by assignee.")] = None,
    owner_id: Annotated[UUID | None, Query(description="Filter by creator.")] = None,
    assigned_to_me: Annotated[
        bool, Query(description="Shorthand for `assignee_id=<me>`.")
    ] = False,
    created_by_me: Annotated[bool, Query(description="Shorthand for `owner_id=<me>`.")] = False,
    unassigned_only: Annotated[bool, Query(description="Only tasks with no assignee.")] = False,
    search: Annotated[
        str | None,
        Query(max_length=200, description="Case-insensitive match on title and description."),
    ] = None,
    sort_by: Annotated[TaskSortField, Query(description="Sort key.")] = (
        TaskSortField.CREATED_AT
    ),
    sort_dir: Annotated[SortDirection, Query(description="Sort direction.")] = (
        SortDirection.DESC
    ),
) -> TaskFilterParams:
    return TaskFilterParams(
        statuses=tuple(status or ()),
        priorities=tuple(priority or ()),
        # Query datetimes go through the same UTC normalisation as body
        # fields, so `?due_before=2026-01-01T00:00:00` means the same thing
        # in both places.
        due_before=as_utc(due_before) if due_before else None,
        due_after=as_utc(due_after) if due_after else None,
        has_due_date=has_due_date,
        overdue_only=overdue_only,
        assignee_id=assignee_id,
        owner_id=owner_id,
        assigned_to_me=assigned_to_me,
        created_by_me=created_by_me,
        unassigned_only=unassigned_only,
        search=search.strip() if search and search.strip() else None,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )


PaginationDep = Annotated[PaginationParams, Depends(pagination_params)]
TaskFilterDep = Annotated[TaskFilterParams, Depends(task_filter_params)]
