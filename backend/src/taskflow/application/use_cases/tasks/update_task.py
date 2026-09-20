"""Partially update a task."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from taskflow.application.dto.commands import UpdateTaskCommand
from taskflow.application.dto.common import is_set
from taskflow.application.dto.views import TaskView
from taskflow.application.ports import Clock, EventPublisher, UnitOfWork
from taskflow.application.use_cases.hydration import hydrate_task
from taskflow.domain.entities import Task
from taskflow.domain.errors import EntityNotFoundError, PermissionDeniedError
from taskflow.domain.value_objects import TaskDescription, TaskTitle


class UpdateTask:
    """Applies a PATCH.

    Two different permission levels are checked, because they are two
    different rules: rewriting a task is the owner's privilege, while moving
    it along its lifecycle is also the assignee's job. A single
    "can_edit" check would either lock assignees out of their own work or
    let them rewrite someone else's task.
    """

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

    async def execute(self, command: UpdateTaskCommand) -> TaskView:
        now = self._clock.now()

        async with self._uow as uow:
            task = await uow.tasks.get(command.task_id)
            # 404 rather than 403: a 403 would confirm the id exists.
            if task is None or not task.is_visible_to(command.actor_id):
                raise EntityNotFoundError(
                    "Task not found.", details={"task_id": str(command.task_id)}
                )

            wants_content_change = any(
                is_set(value)
                for value in (
                    command.title,
                    command.description,
                    command.priority,
                    command.due_date,
                    command.assignee_id,
                )
            )
            if wants_content_change and not task.is_managed_by(command.actor_id):
                raise PermissionDeniedError(
                    "Only the task owner can edit its content or assignment.",
                    details={"task_id": str(task.id)},
                )
            if is_set(command.status) and not task.can_change_status(command.actor_id):
                raise PermissionDeniedError(
                    "You are not allowed to change the status of this task.",
                    details={"task_id": str(task.id)},
                )

            if is_set(command.title):
                task.rename(TaskTitle(command.title), now=now)
            if is_set(command.description):
                task.change_description(TaskDescription(command.description), now=now)
            if is_set(command.priority):
                task.change_priority(command.priority, now=now)
            if is_set(command.due_date):
                task.reschedule(command.due_date, actor_id=command.actor_id, now=now)
            if is_set(command.assignee_id):
                # The narrowed value is passed explicitly: re-reading
                # ``command.assignee_id`` inside the helper would widen it back
                # to ``UUID | None | UNSET``.
                await self._apply_assignment(
                    task,
                    assignee_id=command.assignee_id,
                    actor_id=command.actor_id,
                    uow=uow,
                    now=now,
                )
            if is_set(command.status):
                # Applied last so that, in one request, a task can be
                # reassigned *and* completed with both rules evaluated
                # against the already-updated assignment.
                task.change_status(command.status, actor_id=command.actor_id, now=now)

            await uow.tasks.update(task)
            await uow.commit()

            view = await hydrate_task(task, users=uow.users, now=now, actor_id=command.actor_id)

        await self._publisher.publish_many(task.pull_events())
        return view

    async def _apply_assignment(
        self,
        task: Task,
        *,
        assignee_id: UUID | None,
        actor_id: UUID,
        uow: UnitOfWork,
        now: datetime,
    ) -> None:
        if assignee_id is None:
            task.unassign(actor_id=actor_id, now=now)
            return
        assignee = await uow.users.get(assignee_id)
        if assignee is None:
            raise EntityNotFoundError(
                "The user to assign this task to does not exist.",
                details={"field": "assignee_id"},
            )
        task.assign_to(assignee, actor_id=actor_id, now=now)
