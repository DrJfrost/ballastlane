"""Use case orchestration: permissions, transactions, events, read models."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from taskflow.application.dto import (
    UNSET,
    AssignTaskCommand,
    CompleteTaskCommand,
    CreateTaskCommand,
    DeleteTaskCommand,
    GetTaskQuery,
    ListTasksQuery,
    ReopenTaskCommand,
    TaskStatsQuery,
    UpdateTaskCommand,
)
from taskflow.application.use_cases.tasks import (
    AssignTask,
    CompleteTask,
    CreateTask,
    DeleteTask,
    GetTask,
    GetTaskStats,
    ListTasks,
    ReopenTask,
    UpdateTask,
)
from taskflow.domain.enums import TaskPriority, TaskStatus
from taskflow.domain.errors import (
    ConflictError,
    EntityNotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from taskflow.domain.events import TaskAssigned, TaskCompleted
from taskflow.domain.repositories import Pagination, SortDirection, TaskSortField
from tests.conftest import NOW, make_task

pytestmark = pytest.mark.unit


@pytest.fixture
def create_task(populated_uow, clock, publisher) -> CreateTask:
    return CreateTask(uow=populated_uow, clock=clock, publisher=publisher)


@pytest.fixture
def update_task(populated_uow, clock, publisher) -> UpdateTask:
    return UpdateTask(uow=populated_uow, clock=clock, publisher=publisher)


@pytest.fixture
def get_task(populated_uow, clock) -> GetTask:
    return GetTask(uow=populated_uow, clock=clock)


@pytest.fixture
def list_tasks(populated_uow, clock) -> ListTasks:
    return ListTasks(uow=populated_uow, clock=clock)


class TestCreateTask:
    async def test_creates_and_returns_a_hydrated_view(
        self, create_task, owner, populated_uow
    ) -> None:
        view = await create_task.execute(
            CreateTaskCommand(
                actor_id=owner.id,
                title="  Write   the   ADRs  ",
                description="  Trim me  ",
                priority=TaskPriority.HIGH,
            )
        )

        assert view.title == "Write the ADRs"
        assert view.description == "Trim me"
        assert view.status is TaskStatus.TODO
        assert view.priority is TaskPriority.HIGH
        # The owner is resolved so the UI can render a name, not a UUID.
        assert view.owner is not None
        assert view.owner.full_name == owner.full_name.value
        assert view.can_edit is True
        assert populated_uow.committed == 1

    async def test_pre_assigning_publishes_the_assignment_event(
        self, create_task, owner, teammate, publisher
    ) -> None:
        view = await create_task.execute(
            CreateTaskCommand(actor_id=owner.id, title="Review the PR", assignee_id=teammate.id)
        )

        assert view.assignee is not None
        assert view.assignee.id == teammate.id
        assert publisher.names() == ["TaskAssigned"]
        (event,) = publisher.events_of(TaskAssigned)
        assert event.assigned_by == owner.id

    async def test_unknown_assignee_is_rejected_without_committing(
        self, create_task, owner, populated_uow, publisher
    ) -> None:
        with pytest.raises(EntityNotFoundError, match="assign this task to"):
            await create_task.execute(
                CreateTaskCommand(actor_id=owner.id, title="Review the PR", assignee_id=uuid4())
            )

        # The transactional contract: a failed command writes nothing and
        # notifies nobody.
        assert populated_uow.committed == 0
        assert publisher.published == []

    async def test_invalid_title_never_reaches_the_repository(
        self, create_task, owner, populated_uow
    ) -> None:
        with pytest.raises(ValidationError):
            await create_task.execute(CreateTaskCommand(actor_id=owner.id, title="no"))
        assert populated_uow.committed == 0

    async def test_past_deadline_is_rejected(self, create_task, owner) -> None:
        with pytest.raises(ValidationError, match="future"):
            await create_task.execute(
                CreateTaskCommand(
                    actor_id=owner.id,
                    title="Backdated task",
                    due_date=NOW - timedelta(days=1),
                )
            )


class TestGetTask:
    async def test_owner_can_read(self, get_task, owner, populated_uow) -> None:
        task = make_task(owner_id=owner.id, title="Visible to the owner")
        await populated_uow.tasks.add(task)

        view = await get_task.execute(GetTaskQuery(actor_id=owner.id, task_id=task.id))
        assert view.id == task.id

    async def test_assignee_can_read(self, get_task, owner, teammate, populated_uow) -> None:
        task = make_task(owner_id=owner.id, assignee_id=teammate.id)
        await populated_uow.tasks.add(task)

        view = await get_task.execute(GetTaskQuery(actor_id=teammate.id, task_id=task.id))
        # Read allowed, edit denied: both are projected onto the view.
        assert view.can_edit is False
        assert view.can_change_status is True

    async def test_outsider_gets_not_found_not_forbidden(
        self, get_task, owner, outsider, populated_uow
    ) -> None:
        task = make_task(owner_id=owner.id)
        await populated_uow.tasks.add(task)

        # 403 would confirm the id exists; 404 discloses nothing.
        with pytest.raises(EntityNotFoundError):
            await get_task.execute(GetTaskQuery(actor_id=outsider.id, task_id=task.id))

    async def test_missing_task_is_not_found(self, get_task, owner) -> None:
        with pytest.raises(EntityNotFoundError):
            await get_task.execute(GetTaskQuery(actor_id=owner.id, task_id=uuid4()))


class TestUpdateTask:
    async def test_omitted_fields_are_left_alone(
        self, update_task, owner, populated_uow
    ) -> None:
        task = make_task(
            owner_id=owner.id,
            title="Keep this title",
            description="Keep this description",
            priority=TaskPriority.LOW,
            due_date=NOW + timedelta(days=5),
        )
        await populated_uow.tasks.add(task)

        view = await update_task.execute(
            UpdateTaskCommand(actor_id=owner.id, task_id=task.id, priority=TaskPriority.URGENT)
        )

        assert view.priority is TaskPriority.URGENT
        assert view.title == "Keep this title"
        assert view.description == "Keep this description"
        assert view.due_date == NOW + timedelta(days=5)

    async def test_explicit_null_clears_the_deadline(
        self, update_task, owner, populated_uow
    ) -> None:
        task = make_task(owner_id=owner.id, due_date=NOW + timedelta(days=5))
        await populated_uow.tasks.add(task)

        view = await update_task.execute(
            UpdateTaskCommand(actor_id=owner.id, task_id=task.id, due_date=None)
        )
        # The whole reason the UNSET sentinel exists.
        assert view.due_date is None

    async def test_unset_is_distinguishable_from_null(
        self, update_task, owner, populated_uow
    ) -> None:
        due = NOW + timedelta(days=5)
        task = make_task(owner_id=owner.id, due_date=due)
        await populated_uow.tasks.add(task)

        view = await update_task.execute(
            UpdateTaskCommand(
                actor_id=owner.id, task_id=task.id, due_date=UNSET, title="A different title"
            )
        )
        assert view.due_date == due

    async def test_assignee_cannot_rewrite_content(
        self, update_task, owner, teammate, populated_uow
    ) -> None:
        task = make_task(owner_id=owner.id, assignee_id=teammate.id)
        await populated_uow.tasks.add(task)

        with pytest.raises(PermissionDeniedError, match="owner"):
            await update_task.execute(
                UpdateTaskCommand(actor_id=teammate.id, task_id=task.id, title="Hijacked title")
            )

    async def test_assignee_may_change_the_status(
        self, update_task, owner, teammate, populated_uow
    ) -> None:
        task = make_task(owner_id=owner.id, assignee_id=teammate.id)
        await populated_uow.tasks.add(task)

        view = await update_task.execute(
            UpdateTaskCommand(
                actor_id=teammate.id, task_id=task.id, status=TaskStatus.IN_PROGRESS
            )
        )
        assert view.status is TaskStatus.IN_PROGRESS

    async def test_outsider_gets_not_found(
        self, update_task, owner, outsider, populated_uow
    ) -> None:
        task = make_task(owner_id=owner.id)
        await populated_uow.tasks.add(task)

        with pytest.raises(EntityNotFoundError):
            await update_task.execute(
                UpdateTaskCommand(actor_id=outsider.id, task_id=task.id, title="Hijacked title")
            )

    async def test_reassign_and_complete_in_one_request(
        self, update_task, owner, teammate, populated_uow, publisher
    ) -> None:
        task = make_task(owner_id=owner.id)
        await populated_uow.tasks.add(task)

        view = await update_task.execute(
            UpdateTaskCommand(
                actor_id=owner.id,
                task_id=task.id,
                assignee_id=teammate.id,
                status=TaskStatus.DONE,
            )
        )

        assert view.assignee is not None
        assert view.status is TaskStatus.DONE
        # Status is applied last, so both events land and in a sane order.
        assert publisher.names() == ["TaskAssigned", "TaskCompleted"]

    async def test_setting_assignee_to_null_unassigns(
        self, update_task, owner, teammate, populated_uow
    ) -> None:
        task = make_task(owner_id=owner.id, assignee_id=teammate.id)
        await populated_uow.tasks.add(task)

        view = await update_task.execute(
            UpdateTaskCommand(actor_id=owner.id, task_id=task.id, assignee_id=None)
        )
        assert view.assignee is None

    async def test_illegal_transition_is_a_conflict(
        self, update_task, owner, populated_uow
    ) -> None:
        task = make_task(owner_id=owner.id, status=TaskStatus.DONE, completed_at=NOW)
        await populated_uow.tasks.add(task)

        with pytest.raises(ConflictError):
            await update_task.execute(
                UpdateTaskCommand(
                    actor_id=owner.id, task_id=task.id, status=TaskStatus.CANCELLED
                )
            )


class TestLifecycleUseCases:
    async def test_assignee_can_complete(
        self, populated_uow, clock, publisher, owner, teammate
    ) -> None:
        task = make_task(owner_id=owner.id, assignee_id=teammate.id)
        await populated_uow.tasks.add(task)
        use_case = CompleteTask(uow=populated_uow, clock=clock, publisher=publisher)

        view = await use_case.execute(
            CompleteTaskCommand(actor_id=teammate.id, task_id=task.id)
        )

        assert view.status is TaskStatus.DONE
        assert view.completed_at == NOW
        (event,) = publisher.events_of(TaskCompleted)
        assert event.completed_by == teammate.id
        assert event.owner_id == owner.id

    async def test_outsider_cannot_complete(
        self, populated_uow, clock, publisher, owner, outsider
    ) -> None:
        task = make_task(owner_id=owner.id)
        await populated_uow.tasks.add(task)
        use_case = CompleteTask(uow=populated_uow, clock=clock, publisher=publisher)

        with pytest.raises(EntityNotFoundError):
            await use_case.execute(CompleteTaskCommand(actor_id=outsider.id, task_id=task.id))

    async def test_reopen_restores_an_editable_task(
        self, populated_uow, clock, publisher, owner
    ) -> None:
        task = make_task(owner_id=owner.id, status=TaskStatus.DONE, completed_at=NOW)
        await populated_uow.tasks.add(task)
        use_case = ReopenTask(uow=populated_uow, clock=clock, publisher=publisher)

        view = await use_case.execute(ReopenTaskCommand(actor_id=owner.id, task_id=task.id))
        assert view.status is TaskStatus.TODO
        assert view.completed_at is None

    async def test_only_the_owner_can_reassign(
        self, populated_uow, clock, publisher, owner, teammate, outsider
    ) -> None:
        task = make_task(owner_id=owner.id, assignee_id=teammate.id)
        await populated_uow.tasks.add(task)
        use_case = AssignTask(uow=populated_uow, clock=clock, publisher=publisher)

        with pytest.raises(PermissionDeniedError):
            await use_case.execute(
                AssignTaskCommand(
                    actor_id=teammate.id, task_id=task.id, assignee_id=outsider.id
                )
            )

    async def test_assigning_to_a_deactivated_user_is_a_conflict(
        self, populated_uow, clock, publisher, owner, teammate
    ) -> None:
        teammate.deactivate(now=NOW)
        await populated_uow.users.update(teammate)
        task = make_task(owner_id=owner.id)
        await populated_uow.tasks.add(task)
        use_case = AssignTask(uow=populated_uow, clock=clock, publisher=publisher)

        with pytest.raises(ConflictError, match="deactivated"):
            await use_case.execute(
                AssignTaskCommand(actor_id=owner.id, task_id=task.id, assignee_id=teammate.id)
            )

    async def test_only_the_owner_can_delete(
        self, populated_uow, clock, publisher, owner, teammate
    ) -> None:
        task = make_task(owner_id=owner.id, assignee_id=teammate.id)
        await populated_uow.tasks.add(task)
        use_case = DeleteTask(uow=populated_uow, clock=clock, publisher=publisher)

        with pytest.raises(PermissionDeniedError):
            await use_case.execute(DeleteTaskCommand(actor_id=teammate.id, task_id=task.id))

        await use_case.execute(DeleteTaskCommand(actor_id=owner.id, task_id=task.id))
        assert await populated_uow.tasks.get(task.id) is None


class TestListTasks:
    @pytest.fixture(autouse=True)
    async def _dataset(self, populated_uow, owner, teammate, outsider):
        self.overdue = make_task(
            owner_id=owner.id,
            title="Overdue and open",
            due_date=NOW - timedelta(days=2),
            priority=TaskPriority.URGENT,
        )
        self.assigned = make_task(
            owner_id=teammate.id,
            assignee_id=owner.id,
            title="Assigned to the actor",
            priority=TaskPriority.LOW,
            due_date=NOW + timedelta(days=1),
        )
        self.undated = make_task(
            owner_id=owner.id, title="No deadline at all", priority=TaskPriority.HIGH
        )
        self.done = make_task(
            owner_id=owner.id,
            title="Finished work",
            status=TaskStatus.DONE,
            completed_at=NOW,
        )
        self.invisible = make_task(owner_id=outsider.id, title="Someone elses private task")
        for task in (self.overdue, self.assigned, self.undated, self.done, self.invisible):
            await populated_uow.tasks.add(task)

    async def test_scopes_results_to_the_actor(self, list_tasks, owner) -> None:
        page = await list_tasks.execute(ListTasksQuery(actor_id=owner.id))
        titles = {view.title for view in page.items}

        assert "Someone elses private task" not in titles
        assert page.total == 4

    async def test_filters_by_status(self, list_tasks, owner) -> None:
        page = await list_tasks.execute(
            ListTasksQuery(actor_id=owner.id, statuses=(TaskStatus.DONE,))
        )
        assert [v.title for v in page.items] == ["Finished work"]

    async def test_filters_by_priority(self, list_tasks, owner) -> None:
        page = await list_tasks.execute(
            ListTasksQuery(
                actor_id=owner.id, priorities=(TaskPriority.URGENT, TaskPriority.HIGH)
            )
        )
        assert {v.title for v in page.items} == {"Overdue and open", "No deadline at all"}

    async def test_overdue_only(self, list_tasks, owner) -> None:
        page = await list_tasks.execute(ListTasksQuery(actor_id=owner.id, overdue_only=True))
        assert [v.title for v in page.items] == ["Overdue and open"]
        assert page.items[0].is_overdue is True

    async def test_has_due_date_false_returns_undated(self, list_tasks, owner) -> None:
        page = await list_tasks.execute(ListTasksQuery(actor_id=owner.id, has_due_date=False))
        assert {v.title for v in page.items} == {"No deadline at all", "Finished work"}

    async def test_due_window(self, list_tasks, owner) -> None:
        page = await list_tasks.execute(
            ListTasksQuery(
                actor_id=owner.id,
                due_after=NOW,
                due_before=NOW + timedelta(days=3),
            )
        )
        assert [v.title for v in page.items] == ["Assigned to the actor"]

    async def test_inverted_due_window_is_rejected(self, list_tasks, owner) -> None:
        # Catching this here gives a clear 422 instead of a silently empty list.
        with pytest.raises(ValidationError, match="due_before"):
            await list_tasks.execute(
                ListTasksQuery(
                    actor_id=owner.id,
                    due_after=NOW + timedelta(days=5),
                    due_before=NOW,
                )
            )

    async def test_assigned_to_me_shorthand(self, list_tasks, owner) -> None:
        page = await list_tasks.execute(ListTasksQuery(actor_id=owner.id, assigned_to_me=True))
        assert [v.title for v in page.items] == ["Assigned to the actor"]

    async def test_created_by_me_shorthand(self, list_tasks, owner) -> None:
        page = await list_tasks.execute(ListTasksQuery(actor_id=owner.id, created_by_me=True))
        assert "Assigned to the actor" not in {v.title for v in page.items}
        assert page.total == 3

    async def test_search_matches_title_and_description(
        self, list_tasks, owner, populated_uow
    ) -> None:
        await populated_uow.tasks.add(
            make_task(
                owner_id=owner.id,
                title="Nothing special",
                description="mentions kubernetes in the body",
            )
        )
        page = await list_tasks.execute(ListTasksQuery(actor_id=owner.id, search="KUBERNETES"))
        assert [v.title for v in page.items] == ["Nothing special"]

    async def test_sorts_by_business_priority_not_alphabetically(
        self, list_tasks, owner
    ) -> None:
        page = await list_tasks.execute(
            ListTasksQuery(
                actor_id=owner.id,
                sort_by=TaskSortField.PRIORITY,
                sort_dir=SortDirection.DESC,
            )
        )
        # Alphabetically this would start with "medium"; by weight it starts
        # with "urgent".
        assert page.items[0].priority is TaskPriority.URGENT

    async def test_undated_tasks_sort_last_by_due_date(self, list_tasks, owner) -> None:
        page = await list_tasks.execute(
            ListTasksQuery(
                actor_id=owner.id,
                sort_by=TaskSortField.DUE_DATE,
                sort_dir=SortDirection.ASC,
            )
        )
        due_dates = [view.due_date for view in page.items]
        dated = [d for d in due_dates if d is not None]
        # Every dated item precedes every undated one.
        assert due_dates[: len(dated)] == dated

    async def test_pagination_reports_consistent_metadata(self, list_tasks, owner) -> None:
        first = await list_tasks.execute(
            ListTasksQuery(actor_id=owner.id, pagination=Pagination(page=1, page_size=2))
        )
        second = await list_tasks.execute(
            ListTasksQuery(actor_id=owner.id, pagination=Pagination(page=2, page_size=2))
        )

        assert len(first.items) == 2
        assert first.total == second.total == 4
        assert first.total_pages == 2
        assert first.has_next and not first.has_previous
        assert second.has_previous and not second.has_next
        # No overlap: the secondary sort on id guarantees a stable order.
        assert {v.id for v in first.items}.isdisjoint({v.id for v in second.items})

    async def test_page_beyond_the_end_is_empty_but_reports_the_total(
        self, list_tasks, owner
    ) -> None:
        page = await list_tasks.execute(
            ListTasksQuery(actor_id=owner.id, pagination=Pagination(page=99, page_size=10))
        )
        assert list(page.items) == []
        assert page.total == 4


class TestTaskStats:
    async def test_counts_only_visible_tasks(
        self, populated_uow, clock, owner, outsider
    ) -> None:
        await populated_uow.tasks.add(make_task(owner_id=owner.id))
        await populated_uow.tasks.add(
            make_task(owner_id=owner.id, status=TaskStatus.DONE, completed_at=NOW)
        )
        await populated_uow.tasks.add(
            make_task(owner_id=owner.id, due_date=NOW - timedelta(days=1))
        )
        await populated_uow.tasks.add(make_task(owner_id=outsider.id))

        stats = await GetTaskStats(uow=populated_uow, clock=clock).execute(
            TaskStatsQuery(actor_id=owner.id)
        )

        assert stats.total == 3
        assert stats.todo == 2
        assert stats.done == 1
        assert stats.overdue == 1
        assert stats.cancelled == 0
