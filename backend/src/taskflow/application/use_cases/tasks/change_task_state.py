"""Lifecycle transitions: complete, reopen, assign, delete.

Grouped in one module because they share the same five-line shape (load,
authorise, mutate, commit, publish). Splitting them into four files with
identical boilerplate would be ceremony, not clarity.
"""

from __future__ import annotations

from uuid import UUID

from taskflow.application.dto.commands import (
    AssignTaskCommand,
    CompleteTaskCommand,
    DeleteTaskCommand,
    ReopenTaskCommand,
)
from taskflow.application.dto.views import TaskView
from taskflow.application.ports import Clock, EventPublisher, UnitOfWork
from taskflow.application.use_cases.hydration import hydrate_task
from taskflow.domain.entities import Task
from taskflow.domain.errors import EntityNotFoundError, PermissionDeniedError


class _TaskCommandBase:
    def __init__(
        self,
        *,
        uow: UnitOfWork,
        clock: Clock,
        publisher: EventPublisher,
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._publisher = publisher

    @staticmethod
    async def _load_visible(uow: UnitOfWork, task_id: UUID, actor_id: UUID) -> Task:
        task = await uow.tasks.get(task_id)
        if task is None or not task.is_visible_to(actor_id):
            raise EntityNotFoundError("Task not found.", details={"task_id": str(task_id)})
        return task


class CompleteTask(_TaskCommandBase):
    """Mark a task as done. Owner or assignee may do this."""

    async def execute(self, command: CompleteTaskCommand) -> TaskView:
        now = self._clock.now()
        async with self._uow as uow:
            task = await self._load_visible(uow, command.task_id, command.actor_id)
            if not task.can_change_status(command.actor_id):
                raise PermissionDeniedError(
                    "Only the owner or the assignee can complete this task.",
                    details={"task_id": str(task.id)},
                )
            task.complete(actor_id=command.actor_id, now=now)
            await uow.tasks.update(task)
            await uow.commit()
            view = await hydrate_task(task, users=uow.users, now=now, actor_id=command.actor_id)
        await self._publisher.publish_many(task.pull_events())
        return view


class ReopenTask(_TaskCommandBase):
    """Move a closed task back to ``todo``."""

    async def execute(self, command: ReopenTaskCommand) -> TaskView:
        now = self._clock.now()
        async with self._uow as uow:
            task = await self._load_visible(uow, command.task_id, command.actor_id)
            if not task.can_change_status(command.actor_id):
                raise PermissionDeniedError(
                    "Only the owner or the assignee can reopen this task.",
                    details={"task_id": str(task.id)},
                )
            task.reopen(actor_id=command.actor_id, now=now)
            await uow.tasks.update(task)
            await uow.commit()
            view = await hydrate_task(task, users=uow.users, now=now, actor_id=command.actor_id)
        await self._publisher.publish_many(task.pull_events())
        return view


class AssignTask(_TaskCommandBase):
    """(Re)assign or unassign a task. Owner only."""

    async def execute(self, command: AssignTaskCommand) -> TaskView:
        now = self._clock.now()
        async with self._uow as uow:
            task = await self._load_visible(uow, command.task_id, command.actor_id)
            if not task.is_managed_by(command.actor_id):
                raise PermissionDeniedError(
                    "Only the task owner can change its assignment.",
                    details={"task_id": str(task.id)},
                )

            if command.assignee_id is None:
                task.unassign(actor_id=command.actor_id, now=now)
            else:
                assignee = await uow.users.get(command.assignee_id)
                if assignee is None:
                    raise EntityNotFoundError(
                        "The user to assign this task to does not exist.",
                        details={"field": "assignee_id"},
                    )
                task.assign_to(assignee, actor_id=command.actor_id, now=now)

            await uow.tasks.update(task)
            await uow.commit()
            view = await hydrate_task(task, users=uow.users, now=now, actor_id=command.actor_id)
        await self._publisher.publish_many(task.pull_events())
        return view


class DeleteTask(_TaskCommandBase):
    """Hard-delete a task. Owner only."""

    async def execute(self, command: DeleteTaskCommand) -> None:
        async with self._uow as uow:
            task = await self._load_visible(uow, command.task_id, command.actor_id)
            if not task.is_managed_by(command.actor_id):
                raise PermissionDeniedError(
                    "Only the task owner can delete it.",
                    details={"task_id": str(task.id)},
                )
            await uow.tasks.delete(task.id)
            await uow.commit()
