"""Shared response schemas."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from taskflow.domain.repositories import Page


class PageMeta(BaseModel):
    """Pagination metadata, kept separate from the items.

    Returning ``{"items": [...], "meta": {...}}`` rather than a bare array
    means the client can render a pager without a second request, and adding
    a field later does not change the shape of the payload it already parses.
    """

    model_config = ConfigDict(frozen=True)

    page: int = Field(examples=[1])
    page_size: int = Field(examples=[20])
    total: int = Field(examples=[137])
    total_pages: int = Field(examples=[7])
    has_next: bool = Field(examples=[True])
    has_previous: bool = Field(examples=[False])


class PaginatedResponse[T](BaseModel):
    """Generic envelope for every list endpoint."""

    model_config = ConfigDict(frozen=True)

    items: list[T]
    meta: PageMeta

    @classmethod
    def from_page[E](
        cls,
        page: Page[E],
        serialise: Callable[[E], T],
    ) -> PaginatedResponse[T]:
        return cls(
            items=[serialise(item) for item in page.items],
            meta=PageMeta(
                page=page.page,
                page_size=page.page_size,
                total=page.total,
                total_pages=page.total_pages,
                has_next=page.has_next,
                has_previous=page.has_previous,
            ),
        )


class ProblemDetail(BaseModel):
    """RFC 9457 "Problem Details" error body.

    A single, documented error shape for the whole API. Without one, clients
    end up writing ``err.detail || err.message || err.error`` and still miss
    a case; here the frontend reads ``code`` for logic and ``detail`` for
    display, always.
    """

    model_config = ConfigDict(frozen=True)

    type: str = Field(default="about:blank", examples=["about:blank"])
    title: str = Field(examples=["Validation error"])
    status: int = Field(examples=[422])
    detail: str = Field(examples=["Title must be at least 3 characters."])
    code: str = Field(examples=["validation_error"])
    errors: dict[str, Any] | None = Field(
        default=None, examples=[{"field": "title", "min_length": 3}]
    )
    request_id: str | None = Field(default=None, examples=["01J8Z9..."])


class MessageResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    message: str


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str = Field(examples=["ok"])
    version: str = Field(examples=["1.0.0"])
    environment: str = Field(examples=["local"])
    database: str | None = Field(default=None, examples=["ok"])
