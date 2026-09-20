"""Task aggregate behaviour: invariants, transitions, events, permissions."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from taskflow.domain.entities import Task
from taskflow.domain.enums import TaskPriority, TaskStatus
from taskflow.domain.errors import ConflictError, ValidationError
from taskflow.domain.events import (
    TaskAssigned,
    TaskCompleted,
    TaskDueDateChanged,
    TaskUnassigned,
)
from taskflow.domain.value_objects import TaskDescription, TaskTitle
from tests.conftest import NOW, make_task, make_user

pytestmark = pytest.mark.unit


class TestCreate:
    def test_starts_open_unassigned_and_uncompleted(self) -> None:
        owner_id = uuid4()
        task = Task.create(title=TaskTitle("Ship the API"), owner_id=owner_id, now=NOW)

        assert task.status is TaskStatus.TODO
        assert task.priority is TaskPriority.MEDIUM
        assert task.assignee_id is None
        assert task.completed_at is None
        assert task.due_date is None
        assert task.owner_id == owner_id
        assert task.created_at == task.updated_at == NOW

    def test_accepts_a_future_deadline(self) -> None:
        due = NOW + timedelta(days=7)
        task = Task.create(
            title=TaskTitle("Ship the API"), owner_id=uuid4(), now=NOW, due_date=due
        )
        assert task.due_date == due
        assert not task.is_overdue(NOW)

    @pytest.mark.parametrize("offset", [timedelta(days=-1), timedelta(seconds=-1)])
    def test_refuses_a_deadline_in_the_past(self, offset: timedelta) -> None:
        with pytest.raises(ValidationError, match="must be in the future"):
            Task.create(
                title=TaskTitle("Ship the API"),
                owner_id=uuid4(),
                now=NOW,
                due_date=NOW + offset,
            )

    def test_refuses_a_deadline_exactly_now(self) -> None:
        # A task due at this instant is born overdue; the boundary is closed.
        with pytest.raises(ValidationError):
            Task.create(
                title=TaskTitle("Ship the API"), owner_id=uuid4(), now=NOW, due_date=NOW
            )

    def test_refuses_a_naive_deadline(self) -> None:
        with pytest.raises(ValidationError, match="timezone-aware"):
            Task.create(
                title=TaskTitle("Ship the API"),
                owner_id=uuid4(),
                now=NOW,
                due_date=datetime(2030, 1, 1),
            )

    def test_records_no_events_on_creation(self) -> None:
        task = Task.create(title=TaskTitle("Ship the API"), owner_id=uuid4(), now=NOW)
        assert task.pull_events() == []


class TestPermissions:
    def test_owner_can_do_everything(self, owner, teammate) -> None:
        task = make_task(owner_id=owner.id, assignee_id=teammate.id)
        assert task.is_visible_to(owner.id)
        assert task.is_managed_by(owner.id)
        assert task.can_change_status(owner.id)

    def test_assignee_may_move_the_lifecycle_but_not_rewrite(self, owner, teammate) -> None:
        task = make_task(owner_id=owner.id, assignee_id=teammate.id)
        assert task.is_visible_to(teammate.id)
        assert task.can_change_status(teammate.id)
        # The distinction that matters: an assignee is not an editor.
        assert not task.is_managed_by(teammate.id)

    def test_outsider_sees_nothing(self, owner, teammate, outsider) -> None:
        task = make_task(owner_id=owner.id, assignee_id=teammate.id)
        assert not task.is_visible_to(outsider.id)
        assert not task.is_managed_by(outsider.id)
        assert not task.can_change_status(outsider.id)


class TestAssignment:
    def test_assigning_records_an_event(self, owner, teammate) -> None:
        task = make_task(owner_id=owner.id)
        task.assign_to(teammate, actor_id=owner.id, now=NOW)

        assert task.assignee_id == teammate.id
        (event,) = task.pull_events()
        assert isinstance(event, TaskAssigned)
        assert event.assignee_id == teammate.id
        assert event.assigned_by == owner.id
        assert event.occurred_at == NOW

    def test_reassigning_to_the_same_person_is_a_no_op(self, owner, teammate) -> None:
        task = make_task(owner_id=owner.id, assignee_id=teammate.id)
        task.assign_to(teammate, actor_id=owner.id, now=NOW + timedelta(hours=1))

        # No event, and no spurious ``updated_at`` bump that would show up as
        # a phantom change in the UI.
        assert task.pull_events() == []
        assert task.updated_at == NOW

    def test_cannot_assign_to_a_deactivated_user(self, owner) -> None:
        inactive = make_user(email="gone@taskflow.dev", is_active=False)
        task = make_task(owner_id=owner.id)

        with pytest.raises(ConflictError, match="deactivated"):
            task.assign_to(inactive, actor_id=owner.id, now=NOW)
        assert task.assignee_id is None

    def test_unassigning_records_an_event(self, owner, teammate) -> None:
        task = make_task(owner_id=owner.id, assignee_id=teammate.id)
        task.unassign(actor_id=owner.id, now=NOW)

        assert task.assignee_id is None
        (event,) = task.pull_events()
        assert isinstance(event, TaskUnassigned)
        assert event.previous_assignee_id == teammate.id

    def test_unassigning_an_unassigned_task_is_a_no_op(self, owner) -> None:
        task = make_task(owner_id=owner.id)
        task.unassign(actor_id=owner.id, now=NOW)
        assert task.pull_events() == []


class TestLifecycle:
    def test_completing_sets_the_timestamp_and_emits_an_event(self, owner) -> None:
        task = make_task(owner_id=owner.id)
        task.complete(actor_id=owner.id, now=NOW)

        assert task.status is TaskStatus.DONE
        assert task.completed_at == NOW
        (event,) = task.pull_events()
        assert isinstance(event, TaskCompleted)
        assert event.completed_by == owner.id
        assert event.was_overdue is False

    def test_completing_late_flags_the_event_as_overdue(self, owner) -> None:
        task = make_task(owner_id=owner.id, due_date=NOW - timedelta(days=2))
        task.complete(actor_id=owner.id, now=NOW)

        (event,) = task.pull_events()
        assert isinstance(event, TaskCompleted)
        # Drives a different notification, so the flag has to be right.
        assert event.was_overdue is True

    def test_completing_twice_is_a_conflict(self, owner) -> None:
        task = make_task(owner_id=owner.id)
        task.complete(actor_id=owner.id, now=NOW)

        with pytest.raises(ConflictError, match="already completed"):
            task.complete(actor_id=owner.id, now=NOW + timedelta(hours=1))
        # The first completion must be untouched.
        assert task.completed_at == NOW

    def test_reopening_clears_the_completion_timestamp(self, owner) -> None:
        task = make_task(owner_id=owner.id)
        task.complete(actor_id=owner.id, now=NOW)
        task.pull_events()

        task.reopen(actor_id=owner.id, now=NOW + timedelta(days=1))
        assert task.status is TaskStatus.TODO
        # A reopened task showing a completion date would be a data bug and
        # would also violate the database check constraint.
        assert task.completed_at is None

    def test_cannot_reopen_an_open_task(self, owner) -> None:
        task = make_task(owner_id=owner.id)
        with pytest.raises(ConflictError, match="closed task"):
            task.reopen(actor_id=owner.id, now=NOW)

    def test_starting_moves_to_in_progress(self, owner) -> None:
        task = make_task(owner_id=owner.id)
        task.start(actor_id=owner.id, now=NOW)
        assert task.status is TaskStatus.IN_PROGRESS

    @pytest.mark.parametrize(
        ("start", "target"),
        [
            (TaskStatus.TODO, TaskStatus.IN_PROGRESS),
            (TaskStatus.TODO, TaskStatus.DONE),
            (TaskStatus.TODO, TaskStatus.CANCELLED),
            (TaskStatus.IN_PROGRESS, TaskStatus.TODO),
            (TaskStatus.IN_PROGRESS, TaskStatus.DONE),
            (TaskStatus.DONE, TaskStatus.TODO),
            (TaskStatus.CANCELLED, TaskStatus.TODO),
        ],
    )
    def test_allowed_transitions(self, owner, start, target) -> None:
        task = make_task(owner_id=owner.id, status=start, completed_at=NOW)
        task.change_status(target, actor_id=owner.id, now=NOW)
        assert task.status is target

    @pytest.mark.parametrize(
        ("start", "target"),
        [
            (TaskStatus.DONE, TaskStatus.CANCELLED),
            (TaskStatus.CANCELLED, TaskStatus.DONE),
            (TaskStatus.CANCELLED, TaskStatus.IN_PROGRESS),
        ],
    )
    def test_forbidden_transitions(self, owner, start, target) -> None:
        task = make_task(owner_id=owner.id, status=start, completed_at=NOW)
        with pytest.raises(ConflictError, match="Cannot move a task"):
            task.change_status(target, actor_id=owner.id, now=NOW)
        assert task.status is start

    def test_transition_to_the_same_status_is_a_no_op(self, owner) -> None:
        task = make_task(owner_id=owner.id, status=TaskStatus.TODO)
        task.change_status(TaskStatus.TODO, actor_id=owner.id, now=NOW)
        assert task.pull_events() == []


class TestRescheduling:
    def test_moving_the_deadline_records_the_previous_value(self, owner) -> None:
        original = NOW + timedelta(days=3)
        task = make_task(owner_id=owner.id, due_date=original)
        new_due = NOW + timedelta(days=10)

        task.reschedule(new_due, actor_id=owner.id, now=NOW)

        assert task.due_date == new_due
        (event,) = task.pull_events()
        assert isinstance(event, TaskDueDateChanged)
        assert event.previous_due_date == original
        assert event.new_due_date == new_due

    def test_clearing_the_deadline_is_allowed(self, owner) -> None:
        task = make_task(owner_id=owner.id, due_date=NOW + timedelta(days=3))
        task.reschedule(None, actor_id=owner.id, now=NOW)

        assert task.due_date is None
        (event,) = task.pull_events()
        assert isinstance(event, TaskDueDateChanged)
        assert event.new_due_date is None

    def test_cannot_reschedule_into_the_past(self, owner) -> None:
        task = make_task(owner_id=owner.id)
        with pytest.raises(ValidationError, match="must be in the future"):
            task.reschedule(NOW - timedelta(days=1), actor_id=owner.id, now=NOW)

    def test_rescheduling_to_the_same_value_is_a_no_op(self, owner) -> None:
        due = NOW + timedelta(days=3)
        task = make_task(owner_id=owner.id, due_date=due)
        task.reschedule(due, actor_id=owner.id, now=NOW)
        assert task.pull_events() == []


class TestCancelledTasksAreFrozen:
    def test_content_cannot_change_once_cancelled(self, owner) -> None:
        task = make_task(owner_id=owner.id, status=TaskStatus.CANCELLED)
        for mutate in (
            lambda: task.rename(TaskTitle("A brand new title"), now=NOW),
            lambda: task.change_description(TaskDescription("new"), now=NOW),
            lambda: task.change_priority(TaskPriority.URGENT, now=NOW),
            lambda: task.reschedule(NOW + timedelta(days=5), actor_id=owner.id, now=NOW),
        ):
            with pytest.raises(ConflictError, match="cancelled task"):
                mutate()

    def test_reopening_unfreezes_it(self, owner) -> None:
        task = make_task(owner_id=owner.id, status=TaskStatus.CANCELLED)
        task.reopen(actor_id=owner.id, now=NOW)
        task.rename(TaskTitle("Now editable again"), now=NOW)
        assert task.title.value == "Now editable again"


class TestOverdue:
    @pytest.mark.parametrize(
        ("status", "offset", "expected"),
        [
            (TaskStatus.TODO, timedelta(days=-1), True),
            (TaskStatus.IN_PROGRESS, timedelta(days=-1), True),
            # A finished task that was late is history, not a to-do.
            (TaskStatus.DONE, timedelta(days=-1), False),
            (TaskStatus.CANCELLED, timedelta(days=-1), False),
            (TaskStatus.TODO, timedelta(days=1), False),
        ],
    )
    def test_overdue_requires_an_open_status_and_a_past_deadline(
        self, owner, status, offset, expected
    ) -> None:
        task = make_task(
            owner_id=owner.id,
            status=status,
            due_date=NOW + offset,
            completed_at=NOW,
        )
        assert task.is_overdue(NOW) is expected

    def test_a_task_without_a_deadline_is_never_overdue(self, owner) -> None:
        task = make_task(owner_id=owner.id, due_date=None)
        assert task.is_overdue(NOW) is False
        assert task.days_until_due(NOW) is None

    def test_days_until_due(self, owner) -> None:
        task = make_task(owner_id=owner.id, due_date=NOW + timedelta(days=5, hours=2))
        assert task.days_until_due(NOW) == 5


class TestIdentity:
    def test_equality_is_by_id_not_by_attributes(self, owner) -> None:
        task_id = uuid4()
        one = make_task(owner_id=owner.id, task_id=task_id, title="Original title")
        two = make_task(owner_id=owner.id, task_id=task_id, title="Different title")

        # Same aggregate, loaded twice and mutated in one copy.
        assert one == two
        assert len({one, two}) == 1

    def test_different_ids_are_different_tasks(self, owner) -> None:
        assert make_task(owner_id=owner.id) != make_task(owner_id=owner.id)

    def test_not_equal_to_other_types(self, owner) -> None:
        assert make_task(owner_id=owner.id) != "not a task"


class TestEventDraining:
    def test_pull_events_clears_the_buffer(self, owner, teammate) -> None:
        task = make_task(owner_id=owner.id)
        task.assign_to(teammate, actor_id=owner.id, now=NOW)

        assert task.has_pending_events
        assert len(task.pull_events()) == 1
        # Draining twice must not re-publish; duplicated notifications are
        # exactly what this guarantees against.
        assert task.pull_events() == []
        assert not task.has_pending_events
