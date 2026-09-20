"""Time port."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    """Source of the current time.

    Injected rather than calling ``datetime.now`` inline so that every
    time-dependent rule (overdue detection, token expiry, due-date
    validation) is deterministic under test. A fake clock replaces a pile of
    brittle ``freezegun`` patches with one constructor argument.
    """

    def now(self) -> datetime:
        """Return the current instant as a timezone-aware UTC datetime."""
        ...
