"""Reusable Pydantic field types for the HTTP edge."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, ConfigDict


def as_utc(value: datetime) -> datetime:
    """Normalise an inbound datetime to timezone-aware UTC.

    Pydantic accepts both ``2026-01-01T10:00:00`` (naive) and
    ``2026-01-01T10:00:00+02:00``. The domain rejects naive values outright,
    so the decision is made once, here: a timestamp without an offset is read
    as UTC rather than as the server's local timezone -- otherwise the very
    same request would mean different instants depending on which machine
    handled it.

    Shared by request bodies and query parameters so ``?due_before=`` and
    ``{"due_date": ...}`` cannot drift apart.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


#: A datetime field that is always aware UTC once parsed.
UtcDateTime = Annotated[datetime, AfterValidator(as_utc)]

#: Request bodies reject unknown keys. Pydantic ignores them by default, so a
#: client typo such as ``asignee_id`` is silently dropped and the caller sees
#: a 200 with nothing changed. A 422 naming the unexpected field turns a
#: confusing non-bug into an obvious one.
STRICT_BODY = ConfigDict(extra="forbid")
