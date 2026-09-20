"""Resolve the actor behind an access token."""

from __future__ import annotations

from taskflow.application.dto.views import AuthenticatedUserView
from taskflow.application.ports import TokenService, TokenType, UnitOfWork
from taskflow.domain.errors import AuthenticationError


class ResolveCurrentUser:
    """Backs the ``current_user`` dependency.

    Deliberately a use case and not inline logic in the router: "who is
    calling, and are they still allowed to call" is an application rule, and
    keeping it here means it can be tested without spinning up HTTP.
    """

    def __init__(self, *, uow: UnitOfWork, tokens: TokenService) -> None:
        self._uow = uow
        self._tokens = tokens

    async def execute(self, access_token: str) -> AuthenticatedUserView:
        payload = self._tokens.decode(access_token, expected_type=TokenType.ACCESS)

        async with self._uow as uow:
            user = await uow.users.get(payload.subject)

        if user is None:
            raise AuthenticationError("The account for this token no longer exists.")
        if not user.is_active:
            raise AuthenticationError(
                "This account has been deactivated.", details={"reason": "inactive"}
            )
        return AuthenticatedUserView.from_entity(user)
