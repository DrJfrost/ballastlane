"""Exchange a refresh token for a fresh token pair."""

from __future__ import annotations

from taskflow.application.dto.commands import RefreshTokenCommand
from taskflow.application.dto.views import TokenPairView
from taskflow.application.ports import TokenService, TokenType, UnitOfWork
from taskflow.domain.errors import AuthenticationError


class RefreshAccessToken:
    """Rotates the token pair.

    The user is re-loaded on every refresh rather than trusted from the token
    claims. Tokens are stateless, so a deactivated account would otherwise
    keep minting valid access tokens until the refresh token expired --
    revocation that takes days to take effect is not revocation.
    """

    def __init__(self, *, uow: UnitOfWork, tokens: TokenService) -> None:
        self._uow = uow
        self._tokens = tokens

    async def execute(self, command: RefreshTokenCommand) -> TokenPairView:
        payload = self._tokens.decode(command.refresh_token, expected_type=TokenType.REFRESH)

        async with self._uow as uow:
            user = await uow.users.get(payload.subject)

        if user is None:
            raise AuthenticationError("The account for this token no longer exists.")
        if not user.is_active:
            raise AuthenticationError(
                "This account has been deactivated.", details={"reason": "inactive"}
            )

        access = self._tokens.issue(subject=user.id, token_type=TokenType.ACCESS)
        # Refresh-token rotation: the presented token is replaced rather than
        # reused, which shortens the window in which a leaked one is useful.
        refresh = self._tokens.issue(subject=user.id, token_type=TokenType.REFRESH)
        return TokenPairView(
            access_token=access.value,
            refresh_token=refresh.value,
            token_type="bearer",  # noqa: S106 - the OAuth2 scheme name
            expires_in=access.expires_in_seconds,
        )
