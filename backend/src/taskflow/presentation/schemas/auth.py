"""Auth request/response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from taskflow.application.dto import (
    LoginCommand,
    RefreshTokenCommand,
    RegisterUserCommand,
    TokenPairView,
    UserView,
)
from taskflow.presentation.schemas.fields import STRICT_BODY


class RegisterRequest(BaseModel):
    """Signup payload.

    Note the *shallow* validation here -- length and format only. Whether a
    password is acceptable and whether the email is already taken are
    application rules, checked in the use case. Pydantic guards the shape of
    untrusted JSON; it is not where the business lives.
    """

    model_config = STRICT_BODY | ConfigDict(
        json_schema_extra={
            "example": {
                "email": "new.user@taskflow.dev",
                "full_name": "Sam Rivera",
                "password": "Str0ng-Passphrase!",
            }
        }
    )

    email: EmailStr = Field(max_length=254)
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=10, max_length=128)

    def to_command(self) -> RegisterUserCommand:
        return RegisterUserCommand(
            email=str(self.email),
            full_name=self.full_name,
            password=self.password,
        )


class LoginRequest(BaseModel):
    model_config = STRICT_BODY | ConfigDict(
        json_schema_extra={
            "example": {"email": "ada@taskflow.dev", "password": "DemoPassw0rd!2026"}
        }
    )

    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=1, max_length=128)

    def to_command(self) -> LoginCommand:
        return LoginCommand(email=str(self.email), password=self.password)


class RefreshRequest(BaseModel):
    model_config = STRICT_BODY

    refresh_token: str = Field(min_length=1)

    def to_command(self) -> RefreshTokenCommand:
        return RefreshTokenCommand(refresh_token=self.refresh_token)


class TokenResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 - the OAuth2 scheme name, not a secret
    expires_in: int = Field(description="Access token lifetime in seconds.")

    @classmethod
    def from_view(cls, view: TokenPairView) -> TokenResponse:
        return cls(
            access_token=view.access_token,
            refresh_token=view.refresh_token,
            token_type=view.token_type,
            expires_in=view.expires_in,
        )


class UserResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    email: str
    full_name: str
    initials: str
    is_active: bool
    created_at: datetime

    @classmethod
    def from_view(cls, view: UserView) -> UserResponse:
        return cls(
            id=view.id,
            email=view.email,
            full_name=view.full_name,
            initials=view.initials,
            is_active=view.is_active,
            created_at=view.created_at,
        )


class UserSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    email: str
    full_name: str
    initials: str
