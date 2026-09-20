"""Custom SQLAlchemy column types."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Dialect
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """A ``DateTime`` that is guaranteed to be timezone-aware UTC in Python.

    Why this exists: PostgreSQL ``TIMESTAMPTZ`` round-trips an aware datetime
    correctly, but SQLite has no timezone type and hands back a *naive*
    value. Code that compares a loaded ``due_date`` against
    ``datetime.now(UTC)`` then raises ``TypeError: can't compare offset-naive
    and offset-aware datetimes`` -- on SQLite only, so it passes CI on
    Postgres and breaks locally (or vice versa).

    This decorator makes the two backends behave identically:

    * on the way in, reject naive values and normalise to UTC;
    * on the way out, attach UTC when the driver lost the offset.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Refusing to store a naive datetime; pass a timezone-aware value.")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def copy(self, **kwargs: Any) -> UTCDateTime:  # pragma: no cover - SQLAlchemy plumbing
        return UTCDateTime()
