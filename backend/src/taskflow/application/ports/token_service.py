"""JWT / token issuing port."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


@dataclass(frozen=True, slots=True)
class IssuedToken:
    """A freshly minted token and the metadata a client needs to use it."""

    value: str
    token_type: TokenType
    issued_at: datetime
    expires_at: datetime
    jti: UUID

    @property
    def expires_in_seconds(self) -> int:
        """Lifetime in whole seconds, as OAuth2 clients expect in ``expires_in``."""
        return max(0, int((self.expires_at - self.issued_at).total_seconds()))


@dataclass(frozen=True, slots=True)
class TokenPayload:
    """The verified contents of an inbound token."""

    subject: UUID
    token_type: TokenType
    jti: UUID
    issued_at: datetime
    expires_at: datetime


class TokenService(Protocol):
    """Issues and verifies stateless bearer tokens.

    The ``token_type`` round-trip matters: without it a long-lived refresh
    token would be accepted as an access token, so an attacker who captured
    either one would hold a week of access and the short access-token
    lifetime would buy nothing.
    """

    def issue(self, *, subject: UUID, token_type: TokenType) -> IssuedToken: ...

    def decode(self, token: str, *, expected_type: TokenType) -> TokenPayload:
        """Verify signature, expiry and type.

        Raises :class:`taskflow.domain.errors.AuthenticationError` on any
        problem, deliberately without distinguishing "expired" from
        "tampered" in the message sent to clients.
        """
        ...
