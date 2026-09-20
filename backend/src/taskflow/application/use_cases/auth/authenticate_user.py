"""Exchange credentials for a token pair."""

from __future__ import annotations

from taskflow.application.dto.commands import LoginCommand
from taskflow.application.dto.views import TokenPairView
from taskflow.application.ports import (
    Clock,
    PasswordHasher,
    TokenService,
    TokenType,
    UnitOfWork,
)
from taskflow.domain.errors import AuthenticationError, ValidationError
from taskflow.domain.value_objects import Email

#: Same message for "no such user" and "wrong password" on purpose.
_INVALID_CREDENTIALS = "Incorrect email or password."

#: A pre-computed hash of a random string, used to equalise response time
#: when the account does not exist. Without it, a missing user returns in
#: microseconds while a real one costs a full bcrypt verification, which
#: turns login into an account-enumeration oracle.
_DUMMY_PASSWORD = "not-a-real-password-just-for-timing"  # noqa: S105 - deliberate dummy


class AuthenticateUser:
    #: Cached on the class, not the instance: use cases are constructed per
    #: request, so an instance-level cache would re-pay the bcrypt cost on
    #: every failed login and defeat the point.
    _dummy_hash_cache: str | None = None

    def __init__(
        self,
        *,
        uow: UnitOfWork,
        hasher: PasswordHasher,
        tokens: TokenService,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._hasher = hasher
        self._tokens = tokens
        self._clock = clock

    async def execute(self, command: LoginCommand) -> TokenPairView:
        try:
            email = Email(command.email)
        except ValidationError as exc:
            # Do not leak "that is not even an email" vs "wrong password":
            # both are just a failed login to an attacker.
            raise AuthenticationError(_INVALID_CREDENTIALS) from exc

        async with self._uow as uow:
            user = await uow.users.get_by_email(email)

            if user is None:
                self._hasher.verify(command.password, self._dummy_hash())
                raise AuthenticationError(_INVALID_CREDENTIALS)

            if not self._hasher.verify(command.password, user.hashed_password):
                raise AuthenticationError(_INVALID_CREDENTIALS)

            if not user.is_active:
                raise AuthenticationError(
                    "This account has been deactivated.", details={"reason": "inactive"}
                )

            # Transparent upgrade path when hashing parameters are hardened:
            # the only moment we legitimately hold the plaintext.
            if self._hasher.needs_rehash(user.hashed_password):
                user.change_password(self._hasher.hash(command.password), now=self._clock.now())
                await uow.users.update(user)
                await uow.commit()

        access = self._tokens.issue(subject=user.id, token_type=TokenType.ACCESS)
        refresh = self._tokens.issue(subject=user.id, token_type=TokenType.REFRESH)
        return TokenPairView(
            access_token=access.value,
            refresh_token=refresh.value,
            # The OAuth2 scheme name, which the linter mistakes for a
            # hardcoded credential because of the parameter name.
            token_type="bearer",  # noqa: S106
            expires_in=access.expires_in_seconds,
        )

    def _dummy_hash(self) -> str:
        if AuthenticateUser._dummy_hash_cache is None:
            AuthenticateUser._dummy_hash_cache = self._hasher.hash(_DUMMY_PASSWORD)
        return AuthenticateUser._dummy_hash_cache
