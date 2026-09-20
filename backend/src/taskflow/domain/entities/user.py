"""User aggregate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from taskflow.domain.entities.base import AggregateRoot
from taskflow.domain.errors import ConflictError
from taskflow.domain.value_objects import Email, PersonName


@dataclass(eq=False, slots=True)
class User(AggregateRoot):
    """A person who can own and be assigned tasks.

    The aggregate never sees a plaintext password: hashing happens in an
    infrastructure adapter behind the ``PasswordHasher`` port, so the domain
    has no opinion (and no dependency) on bcrypt vs. argon2.
    """

    id: UUID
    email: Email
    full_name: PersonName
    hashed_password: str
    created_at: datetime
    updated_at: datetime
    is_active: bool = True

    @classmethod
    def register(
        cls,
        *,
        email: Email,
        full_name: PersonName,
        hashed_password: str,
        now: datetime,
        user_id: UUID | None = None,
    ) -> User:
        """Factory for a brand-new, active user."""
        return cls(
            id=user_id or uuid4(),
            email=email,
            full_name=full_name,
            hashed_password=hashed_password,
            created_at=now,
            updated_at=now,
            is_active=True,
        )

    def rename(self, full_name: PersonName, *, now: datetime) -> None:
        if full_name == self.full_name:
            return
        self.full_name = full_name
        self.updated_at = now

    def change_password(self, hashed_password: str, *, now: datetime) -> None:
        if not hashed_password:
            raise ConflictError("Hashed password must not be empty.")
        self.hashed_password = hashed_password
        self.updated_at = now

    def deactivate(self, *, now: datetime) -> None:
        if not self.is_active:
            raise ConflictError("User is already deactivated.")
        self.is_active = False
        self.updated_at = now

    def activate(self, *, now: datetime) -> None:
        if self.is_active:
            raise ConflictError("User is already active.")
        self.is_active = True
        self.updated_at = now

    @property
    def can_be_assigned_work(self) -> bool:
        return self.is_active

    def __eq__(self, other: object) -> bool:
        return isinstance(other, User) and other.id == self.id

    def __hash__(self) -> int:
        return hash(("User", self.id))
