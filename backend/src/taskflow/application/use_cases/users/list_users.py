"""List users, for the assignee picker."""

from __future__ import annotations

from taskflow.application.dto.commands import ListUsersQuery
from taskflow.application.dto.views import UserSummaryView
from taskflow.application.ports import UnitOfWork
from taskflow.domain.repositories import Page, UserFilter


class ListUsers:
    """Returns a paged directory of teammates.

    Exposed as *summaries* only. The assignee dropdown needs a name and an
    id; it does not need password hashes, staff flags or timestamps, and an
    endpoint that returns them is an endpoint that will eventually leak them.
    """

    def __init__(self, *, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, query: ListUsersQuery) -> Page[UserSummaryView]:
        filters = UserFilter(
            is_active=True if query.active_only else None,
            search=query.search,
        )
        async with self._uow as uow:
            page = await uow.users.find(filters, query.pagination)
        return page.map(UserSummaryView.from_entity)
