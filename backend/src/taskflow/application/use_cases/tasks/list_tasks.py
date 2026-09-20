"""List tasks with filtering, sorting and pagination."""

from __future__ import annotations

from datetime import datetime

from taskflow.application.dto.commands import ListTasksQuery
from taskflow.application.dto.views import TaskView
from taskflow.application.ports import Clock, UnitOfWork
from taskflow.application.use_cases.hydration import hydrate_task_page
from taskflow.domain.errors import ValidationError
from taskflow.domain.repositories import Page, TaskFilter, TaskSorting


class ListTasks:
    """Translates a query DTO into a repository filter.

    The important line is ``visible_to=query.actor_id``: scoping happens in
    the filter that reaches SQL, not by post-filtering a page in Python.
    Filtering after pagination is the classic version of this bug -- it
    returns short pages and wrong totals, and still fetches rows the caller
    may not see.
    """

    def __init__(self, *, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(self, query: ListTasksQuery) -> Page[TaskView]:
        now = self._clock.now()
        filters = self._build_filter(query, now=now)
        sorting = TaskSorting(field=query.sort_by, direction=query.sort_dir)

        async with self._uow as uow:
            page = await uow.tasks.find(filters, query.pagination, sorting)
            return await hydrate_task_page(
                page, users=uow.users, now=now, actor_id=query.actor_id
            )

    def _build_filter(self, query: ListTasksQuery, *, now: datetime) -> TaskFilter:
        if (
            query.due_before is not None
            and query.due_after is not None
            and query.due_before < query.due_after
        ):
            raise ValidationError(
                "'due_before' must be later than 'due_after'.",
                details={"fields": ["due_before", "due_after"]},
            )

        assignee_id = query.assignee_id
        if query.assigned_to_me:
            assignee_id = query.actor_id

        owner_id = query.owner_id
        if query.created_by_me:
            owner_id = query.actor_id

        return TaskFilter(
            visible_to=query.actor_id,
            owner_id=owner_id,
            assignee_id=assignee_id,
            unassigned_only=query.unassigned_only,
            statuses=query.statuses,
            priorities=query.priorities,
            due_before=query.due_before,
            due_after=query.due_after,
            has_due_date=query.has_due_date,
            is_overdue_at=now if query.overdue_only else None,
            search=query.search,
        )
