"""Create a task, optionally pre-assigned."""

from __future__ import annotations

from taskflow.application.dto.commands import CreateTaskCommand
from taskflow.application.dto.views import TaskView
from taskflow.application.ports import Clock, EventPublisher, UnitOfWork
from taskflow.application.use_cases.hydration import hydrate_task
from taskflow.domain.entities import Task
from taskflow.domain.errors import EntityNotFoundError
from taskflow.domain.value_objects import TaskDescription, TaskTitle


class CreateTask:
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

    async def execute(self, command: CreateTaskCommand) -> TaskView:
        now = self._clock.now()
        # Value objects validate first, so a bad title never reaches the DB.
        title = TaskTitle(command.title)
        description = TaskDescription(command.description)

        async with self._uow as uow:
            task = Task.create(
                title=title,
                description=description,
                owner_id=command.actor_id,
                priority=command.priority,
                due_date=command.due_date,
                now=now,
            )

            if command.assignee_id is not None:
                assignee = await uow.users.get(command.assignee_id)
                if assignee is None:
                    raise EntityNotFoundError(
                        "The user to assign this task to does not exist.",
                        details={"field": "assignee_id"},
                    )
                task.assign_to(assignee, actor_id=command.actor_id, now=now)

            await uow.tasks.add(task)
            await uow.commit()

            # Read back inside the same UoW so the response reflects exactly
            # what was persisted (and resolves the owner/assignee names).
            view = await hydrate_task(task, users=uow.users, now=now, actor_id=command.actor_id)

        # Only after a successful commit.
        await self._publisher.publish_many(task.pull_events())
        return view
