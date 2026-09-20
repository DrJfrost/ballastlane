"""Repository *ports*.

These are the interfaces the domain needs in order to persist and query
aggregates. They are declared with :class:`typing.Protocol` rather than
``abc.ABC`` so that adapters (SQLAlchemy in production, plain dicts in unit
tests) satisfy them structurally, without inheriting from -- and therefore
without importing -- the domain. That is dependency inversion with zero
coupling in the concrete direction.
"""

from taskflow.domain.repositories.pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    Page,
    Pagination,
)
from taskflow.domain.repositories.task_repository import (
    SortDirection,
    TaskFilter,
    TaskRepository,
    TaskSortField,
    TaskSorting,
)
from taskflow.domain.repositories.user_repository import UserFilter, UserRepository

__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "Page",
    "Pagination",
    "SortDirection",
    "TaskFilter",
    "TaskRepository",
    "TaskSortField",
    "TaskSorting",
    "UserFilter",
    "UserRepository",
]
