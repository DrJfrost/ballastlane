"""Unit of Work port."""

from __future__ import annotations

from types import TracebackType
from typing import Protocol, Self

from taskflow.domain.repositories import TaskRepository, UserRepository


class UnitOfWork(Protocol):
    """One business transaction, spanning several repositories.

    Without this, "create the task and assign it" would be two independent
    commits, and a failure in between would leave an unassigned orphan. With
    it, a use case reads as a single atomic block:

    .. code-block:: python

        async with self._uow as uow:
            ...
            await uow.commit()

    ``__aexit__`` rolls back by default, so forgetting to call ``commit()``
    fails closed (nothing is written) instead of fails open.
    """

    tasks: TaskRepository
    users: UserRepository

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
