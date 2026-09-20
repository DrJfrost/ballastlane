"""SQLAlchemy Unit of Work."""

from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from taskflow.domain.errors import AlreadyExistsError, ConflictError
from taskflow.domain.repositories import TaskRepository, UserRepository
from taskflow.infrastructure.db.repositories.task_repository import (
    SqlAlchemyTaskRepository,
)
from taskflow.infrastructure.db.repositories.user_repository import (
    SqlAlchemyUserRepository,
)


class SqlAlchemyUnitOfWork:
    """One session, one transaction, two repositories.

    The session is created lazily on ``__aenter__`` and always closed on
    exit, so a use case that raises cannot leak a connection back into the
    pool mid-transaction.
    """

    #: Declared as the *ports*, not the concrete adapters: callers depend on
    #: the interface, and it is what makes this class satisfy the
    #: ``UnitOfWork`` Protocol (whose attribute types are invariant).
    #: Only usable inside the ``async with`` block.
    users: UserRepository
    tasks: TaskRepository

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self.users = SqlAlchemyUserRepository(self._session)
        self.tasks = SqlAlchemyTaskRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        session = self._require_session()
        try:
            # Rollback is unconditional and harmless after a commit: it
            # discards whatever was *not* committed. Making it the default
            # means forgetting ``commit()`` loses the write instead of
            # persisting a half-finished operation.
            await session.rollback()
        finally:
            await session.close()
            self._session = None

    async def commit(self) -> None:
        session = self._require_session()
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise _translate_integrity_error(exc) from exc

    async def rollback(self) -> None:
        await self._require_session().rollback()

    def _require_session(self) -> AsyncSession:
        """Fail loudly when used outside its ``async with`` block.

        A real exception rather than ``assert``: assertions are stripped when
        Python runs with ``-O``, so the check would vanish in exactly the
        deployment where a silent ``None`` does the most damage.
        """
        if self._session is None:
            raise RuntimeError(
                "UnitOfWork used outside its context manager; "
                "wrap the work in `async with uow:`."
            )
        return self._session


def _translate_integrity_error(exc: IntegrityError) -> ConflictError:
    """Turn a driver-specific constraint violation into a domain error.

    Without this the API would answer a duplicate signup with a 500 and a
    stack trace mentioning psycopg. The database is the real arbiter of
    uniqueness under concurrency, so its complaint has to be translated
    rather than merely logged.
    """
    message = str(getattr(exc, "orig", exc)).lower()

    if "uq_users_email" in message or ("email" in message and "unique" in message):
        return AlreadyExistsError(
            "An account with this email already exists.", details={"field": "email"}
        )
    if "task_completed_at_consistent" in message:
        return ConflictError(
            "Task completion state is inconsistent.",
            details={"constraint": "task_completed_at_consistent"},
        )
    if "foreign key" in message or "foreignkey" in message:
        return ConflictError(
            "A referenced record does not exist.", details={"constraint": "foreign_key"}
        )
    return ConflictError("The operation conflicts with existing data.")
