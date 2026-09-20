"""Domain-event routing and the Celery jobs themselves."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from taskflow.domain.events import (
    DomainEvent,
    TaskAssigned,
    TaskCompleted,
    TaskDueDateChanged,
    TaskUnassigned,
)
from taskflow.infrastructure.tasks.event_publisher import (
    CeleryEventPublisher,
    InMemoryEventPublisher,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def sent(monkeypatch) -> list[tuple[str, dict]]:
    """Capture what would have gone onto the broker."""
    captured: list[tuple[str, dict]] = []

    def fake_send(name: str, kwargs: dict) -> None:
        captured.append((name, kwargs))

    monkeypatch.setattr(CeleryEventPublisher, "_send", staticmethod(fake_send))
    return captured


class TestCeleryEventPublisherRouting:
    async def test_assignment_becomes_a_notification_job(self, sent) -> None:
        task_id, assignee_id, actor_id = uuid4(), uuid4(), uuid4()
        event = TaskAssigned(
            occurred_at=NOW,
            task_id=task_id,
            task_title="Review the deploy plan",
            assignee_id=assignee_id,
            assigned_by=actor_id,
        )

        await CeleryEventPublisher().publish(event)

        assert len(sent) == 1
        name, kwargs = sent[0]
        assert name == "taskflow.notify_task_assigned"
        # UUIDs are stringified: Celery serialises with JSON, and a raw UUID
        # is not JSON-serialisable.
        assert kwargs == {
            "task_id": str(task_id),
            "task_title": "Review the deploy plan",
            "assignee_id": str(assignee_id),
            "assigned_by": str(actor_id),
        }
        assert all(isinstance(value, str) for value in kwargs.values())

    async def test_completion_becomes_a_notification_job(self, sent) -> None:
        event = TaskCompleted(
            occurred_at=NOW,
            task_id=uuid4(),
            task_title="Ship it",
            completed_by=uuid4(),
            owner_id=uuid4(),
            was_overdue=True,
        )
        await CeleryEventPublisher().publish(event)

        name, kwargs = sent[0]
        assert name == "taskflow.notify_task_completed"
        assert kwargs["was_overdue"] is True

    async def test_due_date_change_serialises_the_new_date(self, sent) -> None:
        event = TaskDueDateChanged(
            occurred_at=NOW,
            task_id=uuid4(),
            previous_due_date=NOW,
            new_due_date=datetime(2027, 1, 1, tzinfo=UTC),
            changed_by=uuid4(),
        )
        await CeleryEventPublisher().publish(event)

        name, kwargs = sent[0]
        assert name == "taskflow.notify_due_date_changed"
        assert kwargs["new_due_date"] == "2027-01-01T00:00:00+00:00"

    async def test_a_cleared_due_date_serialises_as_null(self, sent) -> None:
        event = TaskDueDateChanged(
            occurred_at=NOW,
            task_id=uuid4(),
            previous_due_date=NOW,
            new_due_date=None,
            changed_by=uuid4(),
        )
        await CeleryEventPublisher().publish(event)
        assert sent[0][1]["new_due_date"] is None

    async def test_unassignment_is_logged_but_not_notified(self, sent) -> None:
        # "You no longer have this task" is noise, not news.
        event = TaskUnassigned(
            occurred_at=NOW,
            task_id=uuid4(),
            previous_assignee_id=uuid4(),
            unassigned_by=uuid4(),
        )
        await CeleryEventPublisher().publish(event)
        assert sent == []

    async def test_an_unrouted_event_is_warned_about_not_crashed_on(self, sent, caplog) -> None:
        class SomethingNew(DomainEvent):
            pass

        with caplog.at_level(logging.WARNING, logger="taskflow.events"):
            await CeleryEventPublisher().publish(SomethingNew(occurred_at=NOW))

        assert sent == []
        assert "unrouted_domain_event" in caplog.text

    async def test_publish_many_dispatches_each_event(self, sent) -> None:
        events = [
            TaskAssigned(
                occurred_at=NOW,
                task_id=uuid4(),
                task_title=f"Task {index}",
                assignee_id=uuid4(),
                assigned_by=uuid4(),
            )
            for index in range(3)
        ]
        await CeleryEventPublisher().publish_many(events)
        assert len(sent) == 3

    async def test_disabled_publisher_sends_nothing(self, sent) -> None:
        await CeleryEventPublisher(enabled=False).publish(
            TaskAssigned(
                occurred_at=NOW,
                task_id=uuid4(),
                task_title="Ignored",
                assignee_id=uuid4(),
                assigned_by=uuid4(),
            )
        )
        assert sent == []

    async def test_a_broker_failure_does_not_fail_the_request(
        self, monkeypatch, caplog
    ) -> None:
        """The write already committed, so a lost email must not become a 500.

        Raising here would tell the user their task was not created, when in
        fact it was -- and they would retry and create a duplicate.
        """

        def exploding_send(name: str, kwargs: dict) -> None:
            raise ConnectionError("redis is down")

        monkeypatch.setattr(CeleryEventPublisher, "_send", staticmethod(exploding_send))

        with caplog.at_level(logging.ERROR, logger="taskflow.events"):
            await CeleryEventPublisher().publish(
                TaskCompleted(
                    occurred_at=NOW,
                    task_id=uuid4(),
                    task_title="Already saved",
                    completed_by=uuid4(),
                    owner_id=uuid4(),
                    was_overdue=False,
                )
            )

        assert "event_dispatch_failed" in caplog.text


class TestInMemoryEventPublisher:
    async def test_records_events_for_assertions(self) -> None:
        publisher = InMemoryEventPublisher()
        event = TaskAssigned(
            occurred_at=NOW,
            task_id=uuid4(),
            task_title="Recorded",
            assignee_id=uuid4(),
            assigned_by=uuid4(),
        )

        await publisher.publish(event)

        assert publisher.published == [event]
        assert publisher.events_of(TaskAssigned) == [event]
        assert publisher.events_of(TaskCompleted) == []

    async def test_clear_resets_the_log(self) -> None:
        publisher = InMemoryEventPublisher()
        await publisher.publish_many(
            [
                TaskUnassigned(
                    occurred_at=NOW,
                    task_id=uuid4(),
                    previous_assignee_id=uuid4(),
                    unassigned_by=uuid4(),
                )
            ]
        )
        assert publisher.published
        publisher.clear()
        assert publisher.published == []


class TestCeleryAppConfiguration:
    def test_only_json_is_accepted(self) -> None:
        """Pickle deserialises arbitrary objects.

        A broker an attacker can write to would then become remote code
        execution on every worker.
        """
        from taskflow.infrastructure.tasks.celery_app import create_celery_app

        app = create_celery_app()
        assert app.conf.accept_content == ["json"]
        assert app.conf.task_serializer == "json"

    def test_acks_late_so_a_killed_worker_redelivers(self) -> None:
        from taskflow.infrastructure.tasks.celery_app import create_celery_app

        app = create_celery_app()
        assert app.conf.task_acks_late is True
        assert app.conf.task_reject_on_worker_lost is True

    def test_the_overdue_scan_is_scheduled(self) -> None:
        from taskflow.infrastructure.tasks.celery_app import create_celery_app

        app = create_celery_app()
        assert "scan-overdue-tasks-daily" in app.conf.beat_schedule
        assert (
            app.conf.beat_schedule["scan-overdue-tasks-daily"]["task"]
            == "taskflow.scan_overdue_tasks"
        )

    def test_runs_in_utc(self) -> None:
        from taskflow.infrastructure.tasks.celery_app import create_celery_app

        app = create_celery_app()
        assert app.conf.timezone == "UTC"
        assert app.conf.enable_utc is True
