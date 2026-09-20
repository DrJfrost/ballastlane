"""Register a new user."""

from __future__ import annotations

from taskflow.application.dto.commands import RegisterUserCommand
from taskflow.application.dto.views import UserView
from taskflow.application.ports import Clock, PasswordHasher, UnitOfWork
from taskflow.domain.entities import User
from taskflow.domain.errors import AlreadyExistsError, ValidationError
from taskflow.domain.value_objects import Email, PersonName

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128


class RegisterUser:
    """Creates an account.

    Password *policy* is an application concern, not a domain one: the
    aggregate only ever holds a hash, so it has no way (and no business) to
    judge the strength of a plaintext it never sees.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWork,
        hasher: PasswordHasher,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._hasher = hasher
        self._clock = clock

    async def execute(self, command: RegisterUserCommand) -> UserView:
        email = Email(command.email)
        full_name = PersonName(command.full_name)
        _validate_password(command.password)

        async with self._uow as uow:
            # Checked here for a friendly 409; the unique index on
            # ``users.email`` is what actually guarantees it under concurrency
            # (two simultaneous signups both pass this check).
            if await uow.users.exists_with_email(email):
                raise AlreadyExistsError(
                    "An account with this email already exists.",
                    details={"field": "email"},
                )

            user = User.register(
                email=email,
                full_name=full_name,
                hashed_password=self._hasher.hash(command.password),
                now=self._clock.now(),
            )
            await uow.users.add(user)
            await uow.commit()

        return UserView.from_entity(user)


def _validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
            details={"field": "password", "min_length": MIN_PASSWORD_LENGTH},
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        # bcrypt silently truncates at 72 bytes; an explicit cap avoids the
        # surprise of two different long passwords both being accepted.
        raise ValidationError(
            f"Password must be at most {MAX_PASSWORD_LENGTH} characters.",
            details={"field": "password", "max_length": MAX_PASSWORD_LENGTH},
        )
    if password.strip() != password:
        raise ValidationError(
            "Password must not start or end with whitespace.",
            details={"field": "password"},
        )
    if password.lower() in _COMMON_PASSWORDS:
        raise ValidationError(
            "This password is too common; please choose another.",
            details={"field": "password"},
        )


_COMMON_PASSWORDS = frozenset(
    {
        "password",
        "password1",
        "password123",
        "1234567890",
        "qwertyuiop",
        "letmein123",
        "iloveyou1",
        "adminadmin",
    }
)
