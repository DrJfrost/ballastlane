"""Read a single task."""

from __future__ import annotations

from taskflow.application.dto.commands import GetTaskQuery
from taskflow.application.dto.views import TaskView
from taskflow.application.ports import Clock, UnitOfWork
from taskflow.application.use_cases.hydration import hydrate_task
from taskflow.domain.errors import EntityNotFoundError


class GetTask:
    def __init__(self, *, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(self, query: GetTaskQuery) -> TaskView:
        now = self._clock.now()
        async with self._uow as uow:
            task = await uow.tasks.get(query.task_id)
            if task is None or not task.is_visible_to(query.actor_id):
                raise EntityNotFoundError(
                    "Task not found.", details={"task_id": str(query.task_id)}
                )
            return await hydrate_task(task, users=uow.users, now=now, actor_id=query.actor_id)
