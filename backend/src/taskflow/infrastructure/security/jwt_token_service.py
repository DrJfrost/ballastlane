"""PyJWT-based token service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from jwt import InvalidTokenError

from taskflow.application.ports import Clock
from taskflow.application.ports.token_service import (
    IssuedToken,
    TokenPayload,
    TokenType,
)
from taskflow.domain.errors import AuthenticationError


class JwtTokenService:
    """Issues and verifies HS256 JWTs.

    Symmetric signing is the right default here: one service both issues and
    verifies, so there is no third party that needs a public key. Moving to
    RS256 later is a change to this adapter only, because the application
    depends on the ``TokenService`` port.
    """

    def __init__(
        self,
        *,
        secret_key: str,
        algorithm: str,
        issuer: str,
        access_ttl: timedelta,
        refresh_ttl: timedelta,
        clock: Clock,
    ) -> None:
        self._secret_key = secret_key
        self._algorithm = algorithm
        self._issuer = issuer
        self._ttl = {TokenType.ACCESS: access_ttl, TokenType.REFRESH: refresh_ttl}
        self._clock = clock

    def issue(self, *, subject: UUID, token_type: TokenType) -> IssuedToken:
        issued_at = self._clock.now()
        expires_at = issued_at + self._ttl[token_type]
        jti = uuid4()

        token = jwt.encode(
            {
                "sub": str(subject),
                "jti": str(jti),
                # Custom claim, checked on decode. Without it the long-lived
                # refresh token would be accepted wherever an access token is,
                # which quietly cancels the short access-token lifetime.
                "typ": token_type.value,
                "iat": int(issued_at.timestamp()),
                "exp": int(expires_at.timestamp()),
                "iss": self._issuer,
            },
            self._secret_key,
            algorithm=self._algorithm,
        )
        return IssuedToken(
            value=token,
            token_type=token_type,
            issued_at=issued_at,
            expires_at=expires_at,
            jti=jti,
        )

    #: Tolerance for clock drift between the machine that signed a token and
    #: the one verifying it. Without any, a few seconds of NTP skew between
    #: replicas rejects tokens that were just issued.
    LEEWAY = timedelta(seconds=10)

    def decode(self, token: str, *, expected_type: TokenType) -> TokenPayload:
        try:
            claims = jwt.decode(
                token,
                self._secret_key,
                # A list, never a wildcard: accepting ``algorithms=["none"]``
                # or letting the token choose is the canonical JWT flaw.
                algorithms=[self._algorithm],
                issuer=self._issuer,
                options={
                    "require": ["exp", "iat", "sub", "jti", "iss"],
                    # Expiry is checked below against the injected clock, not
                    # against ``time.time()``. Letting PyJWT do it would make
                    # this the one place where the Clock port is bypassed --
                    # so a test with a fixed clock could issue a token that
                    # the same service then refuses as expired.
                    "verify_exp": False,
                },
            )
        except InvalidTokenError as exc:
            # One message for expired, tampered, wrong-issuer and malformed.
            # Distinguishing them tells an attacker which part to fix.
            raise AuthenticationError("Invalid or expired token.") from exc

        if claims.get("typ") != expected_type.value:
            raise AuthenticationError(
                "Invalid or expired token.", details={"reason": "wrong_token_type"}
            )

        try:
            subject = UUID(claims["sub"])
            jti = UUID(claims["jti"])
            issued_at = _from_timestamp(claims["iat"])
            expires_at = _from_timestamp(claims["exp"])
        except (KeyError, TypeError, ValueError, OSError, OverflowError) as exc:
            raise AuthenticationError("Invalid or expired token.") from exc

        if expires_at + self.LEEWAY <= self._clock.now():
            raise AuthenticationError(
                "Invalid or expired token.", details={"reason": "expired"}
            )

        return TokenPayload(
            subject=subject,
            token_type=expected_type,
            jti=jti,
            issued_at=issued_at,
            expires_at=expires_at,
        )


def _from_timestamp(value: float) -> datetime:
    return datetime.fromtimestamp(value, tz=UTC)
