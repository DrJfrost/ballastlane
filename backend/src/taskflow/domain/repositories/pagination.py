"""Pagination primitives shared by every repository port."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from math import ceil

from taskflow.domain.errors import ValidationError

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class Pagination:
    """A validated page request.

    ``MAX_PAGE_SIZE`` is a hard cap rather than a suggestion: without it a
    single ``?page_size=1000000`` request can pin a worker and exhaust memory,
    which is a cheap denial-of-service vector on any list endpoint.
    """

    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValidationError(
                "Page must be 1 or greater.", details={"field": "page", "value": self.page}
            )
        if self.page_size < 1:
            raise ValidationError(
                "Page size must be 1 or greater.",
                details={"field": "page_size", "value": self.page_size},
            )
        if self.page_size > MAX_PAGE_SIZE:
            raise ValidationError(
                f"Page size must be at most {MAX_PAGE_SIZE}.",
                details={"field": "page_size", "max": MAX_PAGE_SIZE},
            )

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


@dataclass(frozen=True, slots=True)
class Page[T]:
    """One slice of a larger result set, plus the metadata a client needs."""

    items: Sequence[T] = field(default_factory=tuple)
    total: int = 0
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE

    @property
    def total_pages(self) -> int:
        if self.page_size <= 0:
            return 0
        return ceil(self.total / self.page_size)

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages

    @property
    def has_previous(self) -> bool:
        return self.page > 1

    def map[R](self, transform: Callable[[T], R]) -> Page[R]:
        """Project the items while preserving the pagination metadata.

        Lets a use case turn a ``Page[Task]`` from the repository into the
        ``Page[TaskView]`` it returns, without re-deriving totals.
        """
        return Page(
            items=[transform(item) for item in self.items],
            total=self.total,
            page=self.page,
            page_size=self.page_size,
        )
