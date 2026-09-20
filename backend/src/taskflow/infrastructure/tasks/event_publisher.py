"""Adapters for the ``EventPublisher`` port."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

from taskflow.domain.events import (
    DomainEvent,
    TaskAssigned,
    TaskCompleted,
    TaskDueDateChanged,
    TaskUnassigned,
)

logger = logging.getLogger("taskflow.events")


class CeleryEventPublisher:
    """Turns domain events into Celery jobs.

    The routing table is the whole point of this class: the domain records
    ``TaskAssigned``, and *only this file* knows that it becomes a
    ``taskflow.notify_task_assigned`` message on Redis. Swapping Celery for
    SQS is a change here and nowhere else.
    """

    def __init__(self, *, enabled: bool = True) -> None:
        self._enabled = enabled

    async def publish(self, event: DomainEvent) -> None:
        if not self._enabled:
            logger.debug("event_publishing_disabled", extra={"event": event.name})
            return

        job = self._route(event)
        if job is None:
            return

        name, kwargs = job
        try:
            # ``.delay()`` opens a socket to the broker, which blocks. Running
            # it in a worker thread keeps the event loop free; calling it
            # directly would stall every other in-flight request for the
            # duration of the round trip.
            await asyncio.to_thread(self._send, name, kwargs)
        except Exception:
            # A notification is not worth failing the user's write for. The
            # task was already committed; losing the email is recoverable,
            # and returning a 500 after a successful commit is not.
            logger.exception("event_dispatch_failed", extra={"event": event.name, "job": name})

    async def publish_many(self, events: Sequence[DomainEvent]) -> None:
        for event in events:
            await self.publish(event)

    @staticmethod
    def _send(name: str, kwargs: dict[str, object]) -> None:
        # Imported lazily so that constructing the publisher (and therefore
        # importing the app) does not require a reachable broker.
        from taskflow.infrastructure.tasks.celery_app import celery_app  # noqa: PLC0415

        celery_app.send_task(name, kwargs=kwargs)

    @staticmethod
    def _route(event: DomainEvent) -> tuple[str, dict[str, object]] | None:
        match event:
            case TaskAssigned():
                return (
                    "taskflow.notify_task_assigned",
                    {
                        "task_id": str(event.task_id),
                        "task_title": event.task_title,
                        "assignee_id": str(event.assignee_id),
                        "assigned_by": str(event.assigned_by),
                    },
                )
            case TaskCompleted():
                return (
                    "taskflow.notify_task_completed",
                    {
                        "task_id": str(event.task_id),
                        "task_title": event.task_title,
                        "completed_by": str(event.completed_by),
                        "owner_id": str(event.owner_id),
                        "was_overdue": event.was_overdue,
                    },
                )
            case TaskDueDateChanged():
                return (
                    "taskflow.notify_due_date_changed",
                    {
                        "task_id": str(event.task_id),
                        "new_due_date": (
                            event.new_due_date.isoformat() if event.new_due_date else None
                        ),
                        "changed_by": str(event.changed_by),
                    },
                )
            case TaskUnassigned():
                # Recorded for the audit trail but intentionally not notified:
                # "you no longer have this task" is noise, not news.
                logger.info(
                    "task_unassigned",
                    extra={
                        "task_id": str(event.task_id),
                        "previous_assignee_id": str(event.previous_assignee_id),
                    },
                )
                return None
            case _:
                logger.warning("unrouted_domain_event", extra={"event": event.name})
                return None


class InMemoryEventPublisher:
    """Records events instead of dispatching them.

    Used by the test suite (assert on ``published``) and by local runs with
    ``CELERY_ENABLED=false``, so the API works end-to-end without Redis.
    """

    def __init__(self) -> None:
        self.published: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.published.append(event)
        logger.info("event_recorded", extra={"event": event.name})

    async def publish_many(self, events: Sequence[DomainEvent]) -> None:
        for event in events:
            await self.publish(event)

    def clear(self) -> None:
        self.published.clear()

    def events_of[T: DomainEvent](self, event_type: type[T]) -> list[T]:
        return [e for e in self.published if isinstance(e, event_type)]
