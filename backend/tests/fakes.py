"""In-memory test doubles for the application ports.

These exist so the use cases can be tested at full speed with no database, no
event loop pool and no broker. They are *fakes*, not mocks: they implement
real (if naive) behaviour, so a test that passes against them is asserting on
outcomes rather than on which methods were called.

They satisfy the repository Protocols structurally -- no inheritance -- which
is the practical payoff of using ``typing.Protocol`` for the ports.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self
from uuid import UUID

from taskflow.domain.entities import Task, User
from taskflow.domain.enums import TaskStatus
from taskflow.domain.events import DomainEvent
from taskflow.domain.repositories import (
    Page,
    Pagination,
    SortDirection,
    TaskFilter,
    TaskSortField,
    TaskSorting,
    UserFilter,
)
from taskflow.domain.value_objects import Email


class InMemoryTaskRepository:
    def __init__(self, tasks: dict[UUID, Task] | None = None) -> None:
        self._tasks: dict[UUID, Task] = tasks if tasks is not None else {}

    async def add(self, task: Task) -> None:
        self._tasks[task.id] = task

    async def get(self, task_id: UUID) -> Task | None:
        return self._tasks.get(task_id)

    async def update(self, task: Task) -> None:
        self._tasks[task.id] = task

    async def delete(self, task_id: UUID) -> bool:
        return self._tasks.pop(task_id, None) is not None

    async def count(self, filters: TaskFilter) -> int:
        return len(self._matching(filters))

    async def find(
        self,
        filters: TaskFilter,
        pagination: Pagination,
        sorting: TaskSorting | None = None,
    ) -> Page[Task]:
        matched = self._matching(filters)
        matched = _sort(matched, sorting or TaskSorting())
        window = matched[pagination.offset : pagination.offset + pagination.limit]
        return Page(
            items=window,
            total=len(matched),
            page=pagination.page,
            page_size=pagination.page_size,
        )

    def _matching(self, f: TaskFilter) -> list[Task]:
        return [task for task in self._tasks.values() if _matches(task, f)]


class InMemoryUserRepository:
    def __init__(self, users: dict[UUID, User] | None = None) -> None:
        self._users: dict[UUID, User] = users if users is not None else {}

    async def add(self, user: User) -> None:
        self._users[user.id] = user

    async def get(self, user_id: UUID) -> User | None:
        return self._users.get(user_id)

    async def get_by_email(self, email: Email) -> User | None:
        return next((u for u in self._users.values() if u.email == email), None)

    async def update(self, user: User) -> None:
        self._users[user.id] = user

    async def exists_with_email(self, email: Email) -> bool:
        return await self.get_by_email(email) is not None

    async def get_many(self, user_ids: Sequence[UUID]) -> dict[UUID, User]:
        return {uid: self._users[uid] for uid in user_ids if uid in self._users}

    async def find(self, filters: UserFilter, pagination: Pagination) -> Page[User]:
        matched = [
            user
            for user in self._users.values()
            if (filters.is_active is None or user.is_active == filters.is_active)
            and (
                not filters.search
                or filters.search.lower() in user.full_name.value.lower()
                or filters.search.lower() in user.email.value.lower()
            )
        ]
        matched.sort(key=lambda u: u.full_name.value)
        window = matched[pagination.offset : pagination.offset + pagination.limit]
        return Page(
            items=window,
            total=len(matched),
            page=pagination.page,
            page_size=pagination.page_size,
        )


class InMemoryUnitOfWork:
    """Fake UoW that records whether it was committed.

    ``committed`` lets a test assert the *transactional* contract -- that a
    use case which raises does not commit -- which is otherwise invisible.
    """

    def __init__(
        self,
        *,
        users: InMemoryUserRepository | None = None,
        tasks: InMemoryTaskRepository | None = None,
    ) -> None:
        self.users = users or InMemoryUserRepository()
        self.tasks = tasks or InMemoryTaskRepository()
        self.committed = 0
        self.rolled_back = 0
        self.entered = 0

    async def __aenter__(self) -> Self:
        self.entered += 1
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        self.rolled_back += 1


class RecordingEventPublisher:
    def __init__(self) -> None:
        self.published: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.published.append(event)

    async def publish_many(self, events: Sequence[DomainEvent]) -> None:
        self.published.extend(events)

    def names(self) -> list[str]:
        return [event.name for event in self.published]

    def events_of[T: DomainEvent](self, event_type: type[T]) -> list[T]:
        return [e for e in self.published if isinstance(e, event_type)]


class FakePasswordHasher:
    """Reversible, instant "hashing".

    Real bcrypt costs ~250 ms per call by design. A suite that creates a few
    dozen fixture users would spend most of its runtime in key derivation, so
    the unit tests use this and a dedicated test asserts that the *real*
    adapter behaves correctly.
    """

    prefix = "fake$"

    def __init__(self, *, stale_prefix: str = "old$") -> None:
        self._stale_prefix = stale_prefix

    def hash(self, plain_password: str) -> str:
        return f"{self.prefix}{plain_password}"

    def verify(self, plain_password: str, hashed_password: str) -> bool:
        return hashed_password in (
            f"{self.prefix}{plain_password}",
            f"{self._stale_prefix}{plain_password}",
        )

    def needs_rehash(self, hashed_password: str) -> bool:
        return hashed_password.startswith(self._stale_prefix)


class StubTokenService:
    """Issues predictable, inspectable tokens."""

    def __init__(self, *, clock: object | None = None) -> None:
        self.issued: list[tuple[UUID, str]] = []
        self._clock = clock

    def issue(self, *, subject: UUID, token_type) -> object:
        from taskflow.application.ports.token_service import IssuedToken

        self.issued.append((subject, str(token_type)))
        now = datetime(2026, 1, 1, tzinfo=UTC)
        return IssuedToken(
            value=f"{token_type}:{subject}",
            token_type=token_type,
            issued_at=now,
            expires_at=now + timedelta(minutes=15),
            jti=subject,
        )

    def decode(self, token: str, *, expected_type) -> object:
        from taskflow.application.ports.token_service import TokenPayload
        from taskflow.domain.errors import AuthenticationError

        prefix, _, subject = token.partition(":")
        if prefix != str(expected_type):
            raise AuthenticationError("Invalid or expired token.")
        try:
            parsed = UUID(subject)
        except ValueError as exc:
            raise AuthenticationError("Invalid or expired token.") from exc
        now = datetime(2026, 1, 1, tzinfo=UTC)
        return TokenPayload(
            subject=parsed,
            token_type=expected_type,
            jti=parsed,
            issued_at=now,
            expires_at=now + timedelta(minutes=15),
        )


# --------------------------------------------------------------------- #
# Filtering / sorting helpers, mirroring the SQL adapter semantics
# --------------------------------------------------------------------- #
def _matches(task: Task, f: TaskFilter) -> bool:
    if f.visible_to is not None and not task.is_visible_to(f.visible_to):
        return False
    if f.owner_id is not None and task.owner_id != f.owner_id:
        return False
    if f.assignee_id is not None and task.assignee_id != f.assignee_id:
        return False
    if f.unassigned_only and task.assignee_id is not None:
        return False
    if f.statuses and task.status not in f.statuses:
        return False
    if f.priorities and task.priority not in f.priorities:
        return False
    if f.due_after is not None and (task.due_date is None or task.due_date < f.due_after):
        return False
    if f.due_before is not None and (task.due_date is None or task.due_date > f.due_before):
        return False
    if f.has_due_date is True and task.due_date is None:
        return False
    if f.has_due_date is False and task.due_date is not None:
        return False
    if f.is_overdue_at is not None and not task.is_overdue(f.is_overdue_at):
        return False
    if f.search:
        needle = f.search.lower()
        haystack = f"{task.title.value} {task.description.value}".lower()
        if needle not in haystack:
            return False
    return True


_STATUS_ORDER = {
    TaskStatus.TODO: 0,
    TaskStatus.IN_PROGRESS: 1,
    TaskStatus.DONE: 2,
    TaskStatus.CANCELLED: 3,
}


def _sort(tasks: list[Task], sorting: TaskSorting) -> list[Task]:
    reverse = sorting.direction is SortDirection.DESC
    far_future = datetime.max.replace(tzinfo=UTC)

    match sorting.field:
        case TaskSortField.DUE_DATE:
            # Undated tasks last in both directions, like the SQL adapter.
            dated = [t for t in tasks if t.due_date is not None]
            undated = [t for t in tasks if t.due_date is None]
            dated.sort(key=lambda t: (t.due_date or far_future, t.id), reverse=reverse)
            undated.sort(key=lambda t: t.id)
            return dated + undated
        case TaskSortField.PRIORITY:
            key = lambda t: (t.priority.weight, t.id)  # noqa: E731
        case TaskSortField.STATUS:
            key = lambda t: (_STATUS_ORDER[t.status], t.id)  # noqa: E731
        case TaskSortField.TITLE:
            key = lambda t: (t.title.value, t.id)  # noqa: E731
        case TaskSortField.UPDATED_AT:
            key = lambda t: (t.updated_at, t.id)  # noqa: E731
        case _:
            key = lambda t: (t.created_at, t.id)  # noqa: E731

    return sorted(tasks, key=key, reverse=reverse)
