"""Authentication endpoints."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from taskflow.application.dto import LoginCommand
from taskflow.presentation.dependencies.auth import CurrentUser
from taskflow.presentation.dependencies.use_cases import (
    AuthenticateUserDep,
    RefreshAccessTokenDep,
    RegisterUserDep,
)
from taskflow.presentation.rate_limit import limit
from taskflow.presentation.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from taskflow.presentation.schemas.common import ProblemDetail

router = APIRouter(prefix="/auth", tags=["Authentication"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ProblemDetail, "description": "Invalid credentials."},
    409: {"model": ProblemDetail, "description": "Email already registered."},
    422: {"model": ProblemDetail, "description": "Validation failed."},
    429: {"model": ProblemDetail, "description": "Rate limit exceeded."},
}


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
    responses=_ERRORS,
)
@limit("register")
async def register(
    request: Request,
    response: Response,
    payload: RegisterRequest,
    use_case: RegisterUserDep,
) -> UserResponse:
    """Register a new user.

    Deliberately does *not* return a token: making the client log in right
    afterwards keeps exactly one code path that issues credentials, which is
    one place to audit.
    """
    view = await use_case.execute(payload.to_command())
    return UserResponse.from_view(view)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Exchange credentials for tokens",
    responses=_ERRORS,
)
@limit("login")
async def login(
    request: Request,
    response: Response,
    payload: LoginRequest,
    use_case: AuthenticateUserDep,
) -> TokenResponse:
    """Log in with a JSON body (what the frontend uses)."""
    view = await use_case.execute(payload.to_command())
    return TokenResponse.from_view(view)


@router.post(
    "/token",
    response_model=TokenResponse,
    summary="Log in with an OAuth2 password form",
    description=(
        "Identical to `/login` but accepts `application/x-www-form-urlencoded`, "
        "which is what the **Authorize** button in Swagger UI submits."
    ),
    responses=_ERRORS,
)
@limit("login")
async def login_form(
    request: Request,
    response: Response,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    use_case: AuthenticateUserDep,
) -> TokenResponse:
    # OAuth2 calls the identifier ``username``; ours happens to be an email.
    view = await use_case.execute(LoginCommand(email=form.username, password=form.password))
    return TokenResponse.from_view(view)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Rotate the token pair",
    responses=_ERRORS,
)
@limit("login")
async def refresh(
    request: Request,
    response: Response,
    payload: RefreshRequest,
    use_case: RefreshAccessTokenDep,
) -> TokenResponse:
    view = await use_case.execute(payload.to_command())
    return TokenResponse.from_view(view)


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Describe the authenticated user",
    responses={401: _ERRORS[401]},
)
async def me(current_user: CurrentUser) -> UserResponse:
    """Who am I?

    Used by the frontend on boot to decide between the dashboard and the
    login screen, and to validate a token restored from storage.
    """
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        initials=current_user.initials,
        is_active=current_user.is_active,
        created_at=current_user.created_at,
    )
