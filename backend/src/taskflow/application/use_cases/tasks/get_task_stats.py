"""Dashboard counters."""

from __future__ import annotations

from taskflow.application.dto.commands import TaskStatsQuery
from taskflow.application.dto.views import TaskStatsView
from taskflow.application.ports import Clock, UnitOfWork
from taskflow.domain.enums import TaskStatus
from taskflow.domain.repositories import TaskFilter


class GetTaskStats:
    """Counts per status for the tasks visible to the actor.

    Implemented as seven ``COUNT(*)`` queries rather than loading rows and
    tallying them in Python: the numbers are computed by the database, so
    memory stays flat as the dataset grows. They run sequentially because
    they share one session -- a SQLAlchemy ``AsyncSession`` is not safe to
    use concurrently, and gathering them would raise
    ``InterfaceError: another operation is in progress``.
    """

    def __init__(self, *, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(self, query: TaskStatsQuery) -> TaskStatsView:
        now = self._clock.now()
        base = TaskFilter(visible_to=query.actor_id)

        async with self._uow as uow:
            total = await uow.tasks.count(base)
            per_status = {}
            for status in TaskStatus:
                per_status[status] = await uow.tasks.count(
                    TaskFilter(visible_to=query.actor_id, statuses=(status,))
                )
            overdue = await uow.tasks.count(
                TaskFilter(visible_to=query.actor_id, is_overdue_at=now)
            )
            assigned_to_me = await uow.tasks.count(
                TaskFilter(visible_to=query.actor_id, assignee_id=query.actor_id)
            )

        return TaskStatsView(
            total=total,
            todo=per_status[TaskStatus.TODO],
            in_progress=per_status[TaskStatus.IN_PROGRESS],
            done=per_status[TaskStatus.DONE],
            cancelled=per_status[TaskStatus.CANCELLED],
            overdue=overdue,
            assigned_to_me=assigned_to_me,
        )
