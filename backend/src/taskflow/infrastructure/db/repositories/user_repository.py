"""SQLAlchemy implementation of :class:`UserRepository`."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from taskflow.domain.entities import User
from taskflow.domain.repositories import Page, Pagination, UserFilter
from taskflow.domain.value_objects import Email
from taskflow.infrastructure.db.mappers import user_to_entity, user_to_model, user_values
from taskflow.infrastructure.db.models import UserModel


class SqlAlchemyUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user: User) -> None:
        self._session.add(user_to_model(user))

    async def get(self, user_id: UUID) -> User | None:
        row = await self._session.get(UserModel, user_id)
        return user_to_entity(row) if row is not None else None

    async def get_by_email(self, email: Email) -> User | None:
        # ``email.value`` is already lower-cased by the value object, and rows
        # are written the same way, so a plain equality match hits the unique
        # index. Using ``lower(email) = ...`` here would work too but would
        # force a sequential scan.
        statement = select(UserModel).where(UserModel.email == email.value)
        row = (await self._session.execute(statement)).scalar_one_or_none()
        return user_to_entity(row) if row is not None else None

    async def update(self, user: User) -> None:
        await self._session.execute(
            update(UserModel).where(UserModel.id == user.id).values(**user_values(user))
        )

    async def exists_with_email(self, email: Email) -> bool:
        statement = select(select(UserModel.id).where(UserModel.email == email.value).exists())
        return bool((await self._session.execute(statement)).scalar())

    async def find(self, filters: UserFilter, pagination: Pagination) -> Page[User]:
        criteria = self._criteria(filters)

        count_stmt: Select[tuple[int]] = select(func.count()).select_from(UserModel)
        if criteria:
            count_stmt = count_stmt.where(*criteria)
        total = int((await self._session.execute(count_stmt)).scalar_one())
        if total == 0:
            return Page(items=(), total=0, page=pagination.page, page_size=pagination.page_size)

        statement = (
            select(UserModel)
            .where(*criteria)
            .order_by(UserModel.full_name.asc(), UserModel.id.asc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
        rows = (await self._session.execute(statement)).scalars().all()
        return Page(
            items=[user_to_entity(row) for row in rows],
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
        )

    async def get_many(self, user_ids: Sequence[UUID]) -> dict[UUID, User]:
        """Batch-load by id in a single round trip.

        ``IN`` clauses have a parameter ceiling (roughly 32k on Postgres, 999
        on older SQLite builds), so the ids are chunked. A page of tasks can
        never reach that, but the same method is used by the overdue-scan job
        which processes far more rows.
        """
        if not user_ids:
            return {}

        unique_ids = list(dict.fromkeys(user_ids))
        found: dict[UUID, User] = {}
        chunk_size = 500
        for start in range(0, len(unique_ids), chunk_size):
            chunk = unique_ids[start : start + chunk_size]
            statement = select(UserModel).where(UserModel.id.in_(chunk))
            rows = (await self._session.execute(statement)).scalars().all()
            for row in rows:
                found[row.id] = user_to_entity(row)
        return found

    @staticmethod
    def _criteria(filters: UserFilter) -> list[ColumnElement[bool]]:
        criteria: list[ColumnElement[bool]] = []
        if filters.is_active is not None:
            criteria.append(UserModel.is_active.is_(filters.is_active))
        if filters.search:
            term = f"%{filters.search.strip()}%"
            criteria.append(
                or_(
                    UserModel.full_name.ilike(term),
                    UserModel.email.ilike(term),
                )
            )
        return criteria
