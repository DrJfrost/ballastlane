"""Real and fake clocks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


class SystemClock:
    """The real clock, always timezone-aware UTC.

    ``datetime.now(UTC)`` rather than the deprecated ``datetime.utcnow()``:
    the latter returns a *naive* datetime that merely happens to hold UTC,
    which is how naive values leak into a codebase in the first place.
    """

    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """A controllable clock for tests and for the seed script.

    Lives in production code, not in the test package, because the seeder
    also needs deterministic timestamps to generate a stable demo dataset.
    """

    def __init__(self, moment: datetime) -> None:
        if moment.tzinfo is None:
            raise ValueError("FixedClock requires a timezone-aware datetime.")
        self._moment = moment

    def now(self) -> datetime:
        return self._moment

    def set(self, moment: datetime) -> None:
        self._moment = moment

    def advance(self, **kwargs: float) -> None:
        self._moment += timedelta(**kwargs)
