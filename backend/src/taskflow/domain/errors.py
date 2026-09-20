"""Domain-level error hierarchy.

These errors are deliberately transport-agnostic: the domain does not know
what an "HTTP 404" is. The presentation layer maps each subclass onto a
status code in ``presentation/errors.py``, which keeps the business rules
reusable from a CLI, a Celery worker or a gRPC service.
"""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """Base class for every expected (non-bug) failure in the core."""

    code: str = "domain_error"
    title: str = "Domain error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"{type(self).__name__}({self.message!r}, details={self.details!r})"


class ValidationError(DomainError):
    """An invariant of a value object or entity was violated."""

    code = "validation_error"
    title = "Validation error"


class EntityNotFoundError(DomainError):
    """A referenced aggregate does not exist (or is not visible to the actor)."""

    code = "not_found"
    title = "Resource not found"


class ConflictError(DomainError):
    """The requested transition is illegal for the current state."""

    code = "conflict"
    title = "Conflicting state"


class AlreadyExistsError(ConflictError):
    """A uniqueness constraint would be violated."""

    code = "already_exists"
    title = "Resource already exists"


class PermissionDeniedError(DomainError):
    """The actor is authenticated but not allowed to perform the action."""

    code = "permission_denied"
    title = "Permission denied"


class AuthenticationError(DomainError):
    """Credentials are missing, malformed or invalid."""

    code = "authentication_failed"
    title = "Authentication failed"
