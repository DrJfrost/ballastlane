"""Shared aggregate-root behaviour."""

from __future__ import annotations

from dataclasses import dataclass, field

from taskflow.domain.events import DomainEvent


@dataclass(eq=False, slots=True)
class AggregateRoot:
    """An entity with identity-based equality that can record domain events.

    ``eq=False`` is deliberate: two aggregates are the same thing when their
    ids match, regardless of whether their attributes have drifted (e.g. a
    freshly loaded copy vs. a mutated one).

    ``_events`` is declared ``kw_only`` so that subclasses may add *required*
    fields after it -- without that flag, a base field with a default would
    force every subclass field to have one too.
    """

    _events: list[DomainEvent] = field(
        default_factory=list, repr=False, compare=False, kw_only=True
    )

    def record(self, event: DomainEvent) -> None:
        self._events.append(event)

    def pull_events(self) -> list[DomainEvent]:
        """Return and clear the recorded events (drain semantics)."""
        events, self._events = self._events, []
        return events

    @property
    def has_pending_events(self) -> bool:
        return bool(self._events)
