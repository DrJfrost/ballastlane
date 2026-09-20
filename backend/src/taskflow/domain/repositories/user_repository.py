"""User repository port."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from taskflow.domain.entities.user import User
from taskflow.domain.repositories.pagination import Page, Pagination
from taskflow.domain.value_objects import Email


@dataclass(frozen=True, slots=True)
class UserFilter:
    is_active: bool | None = None
    search: str | None = None


class UserRepository(Protocol):
    """Persistence port for the :class:`User` aggregate."""

    async def add(self, user: User) -> None: ...

    async def get(self, user_id: UUID) -> User | None: ...

    async def get_by_email(self, email: Email) -> User | None: ...

    async def update(self, user: User) -> None: ...

    async def exists_with_email(self, email: Email) -> bool: ...

    async def find(self, filters: UserFilter, pagination: Pagination) -> Page[User]: ...

    async def get_many(self, user_ids: Sequence[UUID]) -> dict[UUID, User]:
        """Batch-load users by id.

        Exists purely to let the list-tasks use case resolve owner and
        assignee names in a single round trip instead of one query per row
        (the classic N+1 that turns a 20-item page into 41 queries).
        """
        ...
