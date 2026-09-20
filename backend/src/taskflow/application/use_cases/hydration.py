"""Read-model hydration helpers."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from taskflow.application.dto.views import TaskView
from taskflow.domain.entities import Task
from taskflow.domain.repositories import Page, UserRepository


async def hydrate_tasks(
    tasks: Sequence[Task],
    *,
    users: UserRepository,
    now: datetime,
    actor_id: UUID,
) -> list[TaskView]:
    """Turn entities into read models, resolving people in one query.

    Collecting the referenced ids up front and issuing a single
    ``WHERE id IN (...)`` keeps a page of tasks at two queries regardless of
    page size. Resolving them lazily per row would make a 20-item page cost
    41 round trips -- the difference is invisible on a seeded dev database
    and very visible in production.
    """
    if not tasks:
        return []

    referenced: set[UUID] = set()
    for task in tasks:
        referenced.add(task.owner_id)
        if task.assignee_id is not None:
            referenced.add(task.assignee_id)

    people = await users.get_many(sorted(referenced))
    return [
        TaskView.from_entity(
            task,
            now=now,
            actor_id=actor_id,
            owner=people.get(task.owner_id),
            assignee=people.get(task.assignee_id) if task.assignee_id else None,
        )
        for task in tasks
    ]


async def hydrate_task_page(
    page: Page[Task],
    *,
    users: UserRepository,
    now: datetime,
    actor_id: UUID,
) -> Page[TaskView]:
    """Same as :func:`hydrate_tasks`, preserving pagination metadata."""
    items = await hydrate_tasks(page.items, users=users, now=now, actor_id=actor_id)
    return Page(items=items, total=page.total, page=page.page, page_size=page.page_size)


async def hydrate_task(
    task: Task,
    *,
    users: UserRepository,
    now: datetime,
    actor_id: UUID,
) -> TaskView:
    views = await hydrate_tasks([task], users=users, now=now, actor_id=actor_id)
    return views[0]
