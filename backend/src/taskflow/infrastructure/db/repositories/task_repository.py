"""SQLAlchemy implementation of :class:`TaskRepository`."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from sqlalchemy import Select, case, delete, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement, UnaryExpression

from taskflow.domain.entities import Task
from taskflow.domain.enums import TaskPriority, TaskStatus
from taskflow.domain.repositories import (
    Page,
    Pagination,
    SortDirection,
    TaskFilter,
    TaskSortField,
    TaskSorting,
)
from taskflow.infrastructure.db.mappers import task_to_entity, task_to_model, task_values
from taskflow.infrastructure.db.models import TaskModel


class SqlAlchemyTaskRepository:
    """Adapter that satisfies the ``TaskRepository`` Protocol structurally.

    Note it does *not* inherit from the port: the dependency points from the
    application inwards, never from infrastructure into an abstract base it
    must keep in sync.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, task: Task) -> None:
        self._session.add(task_to_model(task))

    async def get(self, task_id: UUID) -> Task | None:
        row = await self._session.get(TaskModel, task_id)
        return task_to_entity(row) if row is not None else None

    async def update(self, task: Task) -> None:
        """Persist a mutated aggregate with a targeted ``UPDATE``.

        An explicit statement rather than ``session.merge``: the entity was
        mapped out of the ORM, so merging would re-attach a second copy and
        make the flush order depend on identity-map luck. This writes exactly
        the columns the domain owns and leaves ``created_at`` alone.
        """
        await self._session.execute(
            update(TaskModel).where(TaskModel.id == task.id).values(**task_values(task))
        )

    async def delete(self, task_id: UUID) -> bool:
        result = await self._session.execute(delete(TaskModel).where(TaskModel.id == task_id))
        # ``execute`` is typed as returning ``Result``; a DML statement always
        # yields a ``CursorResult``, which is the one that carries rowcount.
        return bool(cast("CursorResult[Any]", result).rowcount)

    async def find(
        self,
        filters: TaskFilter,
        pagination: Pagination,
        sorting: TaskSorting | None = None,
    ) -> Page[Task]:
        sorting = sorting or TaskSorting()
        criteria = _build_criteria(filters)

        # Total first: two small queries beat loading every matching row to
        # count them in Python, and the client needs `total` for the pager.
        total = await self._scalar_count(criteria)
        if total == 0:
            return Page(items=(), total=0, page=pagination.page, page_size=pagination.page_size)

        statement = (
            select(TaskModel)
            .where(*criteria)
            .order_by(*_order_by(sorting))
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
        rows = (await self._session.execute(statement)).scalars().all()
        return Page(
            items=[task_to_entity(row) for row in rows],
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
        )

    async def count(self, filters: TaskFilter) -> int:
        return await self._scalar_count(_build_criteria(filters))

    async def _scalar_count(self, criteria: list[ColumnElement[bool]]) -> int:
        statement: Select[tuple[int]] = select(func.count()).select_from(TaskModel)
        if criteria:
            statement = statement.where(*criteria)
        return int((await self._session.execute(statement)).scalar_one())


def _build_criteria(filters: TaskFilter) -> list[ColumnElement[bool]]:
    """Translate the filter value object into SQL predicates.

    Everything is a bound parameter; no string interpolation ever reaches the
    query, which is what makes ``?search=`` safe against injection.
    """
    criteria: list[ColumnElement[bool]] = []

    if filters.visible_to is not None:
        # The authorisation boundary, expressed in SQL so it cannot be
        # bypassed by a caller that forgets to post-filter.
        criteria.append(
            or_(
                TaskModel.owner_id == filters.visible_to,
                TaskModel.assignee_id == filters.visible_to,
            )
        )
    if filters.owner_id is not None:
        criteria.append(TaskModel.owner_id == filters.owner_id)
    if filters.assignee_id is not None:
        criteria.append(TaskModel.assignee_id == filters.assignee_id)
    if filters.unassigned_only:
        criteria.append(TaskModel.assignee_id.is_(None))
    if filters.statuses:
        criteria.append(TaskModel.status.in_([s.value for s in filters.statuses]))
    if filters.priorities:
        criteria.append(TaskModel.priority.in_([p.value for p in filters.priorities]))
    if filters.due_after is not None:
        criteria.append(TaskModel.due_date >= filters.due_after)
    if filters.due_before is not None:
        criteria.append(TaskModel.due_date <= filters.due_before)
    if filters.has_due_date is True:
        criteria.append(TaskModel.due_date.is_not(None))
    if filters.has_due_date is False:
        criteria.append(TaskModel.due_date.is_(None))
    if filters.is_overdue_at is not None:
        # Mirrors ``Task.is_overdue``: past deadline *and* still open. A
        # completed task that was late is history, not a to-do.
        criteria.append(TaskModel.due_date.is_not(None))
        criteria.append(TaskModel.due_date < filters.is_overdue_at)
        # Derived from the enum rather than hard-coded, so adding a status
        # cannot leave this predicate quietly out of date.
        criteria.append(TaskModel.status.in_([s.value for s in TaskStatus if s.is_open]))
    if filters.search:
        term = f"%{_escape_like(filters.search.strip())}%"
        criteria.append(
            or_(
                TaskModel.title.ilike(term, escape="\\"),
                TaskModel.description.ilike(term, escape="\\"),
            )
        )
    return criteria


def _escape_like(term: str) -> str:
    """Neutralise LIKE wildcards in user input.

    Without this, a search for ``100%`` matches everything and ``_`` matches
    any character -- surprising rather than dangerous, but still wrong.
    """
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


#: Sorting by the ``priority`` column directly would order it
#: *alphabetically* -- high, low, medium, urgent -- which is not the business
#: order at all. Ranking in SQL keeps sorting correct without denormalising a
#: numeric column into the table.
_PRIORITY_RANK = case(
    {
        TaskPriority.LOW.value: 0,
        TaskPriority.MEDIUM.value: 1,
        TaskPriority.HIGH.value: 2,
        TaskPriority.URGENT.value: 3,
    },
    value=TaskModel.priority,
    else_=-1,
)

#: Same problem for status: the lifecycle order is not the alphabet.
_STATUS_RANK = case(
    {
        TaskStatus.TODO.value: 0,
        TaskStatus.IN_PROGRESS.value: 1,
        TaskStatus.DONE.value: 2,
        TaskStatus.CANCELLED.value: 3,
    },
    value=TaskModel.status,
    else_=-1,
)


def _order_by(sorting: TaskSorting) -> list[UnaryExpression[object]]:
    """Build the ORDER BY clause.

    The requested key is looked up in a whitelist, never interpolated, so an
    arbitrary ``?sort_by=`` cannot reach SQL. A secondary sort on ``id``
    guarantees a *total* order: without it, rows that tie on the chosen sort
    key may come back in a different relative order for each page, so an item
    can silently appear twice, or never, while the user pages through.
    """
    column = {
        TaskSortField.DUE_DATE: TaskModel.due_date,
        TaskSortField.CREATED_AT: TaskModel.created_at,
        TaskSortField.UPDATED_AT: TaskModel.updated_at,
        TaskSortField.PRIORITY: _PRIORITY_RANK,
        TaskSortField.TITLE: TaskModel.title,
        TaskSortField.STATUS: _STATUS_RANK,
    }[sorting.field]

    if sorting.field is TaskSortField.DUE_DATE:
        # Tasks without a deadline sort last in both directions; treating
        # NULL as "very early" would bury the urgent, dated work.
        primary = (
            column.asc().nullslast()
            if sorting.direction is SortDirection.ASC
            else column.desc().nullslast()
        )
    else:
        primary = column.asc() if sorting.direction is SortDirection.ASC else column.desc()

    return [primary, TaskModel.id.asc()]
