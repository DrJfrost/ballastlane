"""Domain event publishing port."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from taskflow.domain.events import DomainEvent


class EventPublisher(Protocol):
    """Hands domain events to the outside world (Celery in production).

    Publishing happens *after* the unit of work commits, so a rolled-back
    transaction can never produce a notification about work that did not
    actually happen.
    """

    async def publish(self, event: DomainEvent) -> None: ...

    async def publish_many(self, events: Sequence[DomainEvent]) -> None: ...
