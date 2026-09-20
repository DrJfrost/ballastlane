"""Authentication dependency."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from taskflow.application.dto import AuthenticatedUserView
from taskflow.domain.errors import AuthenticationError
from taskflow.presentation.dependencies.use_cases import ResolveCurrentUserDep

#: ``auto_error=False`` so a missing header reaches our own handler and comes
#: back as the standard ProblemDetail envelope, instead of FastAPI's default
#: ``{"detail": "Not authenticated"}`` shape that no other endpoint uses.
bearer_scheme = HTTPBearer(
    scheme_name="JWT",
    description="Paste the `access_token` returned by `POST /api/v1/auth/login`.",
    auto_error=False,
)


async def get_current_user(
    request: Request,
    resolve: ResolveCurrentUserDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> AuthenticatedUserView:
    """Resolve and cache the caller for the lifetime of the request."""
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Missing bearer token.")

    user = await resolve.execute(credentials.credentials)

    # Published for the rate limiter, which prefers a per-user bucket over a
    # per-IP one once it knows who is calling.
    request.state.user_id = str(user.id)
    return user


CurrentUser = Annotated[AuthenticatedUserView, Depends(get_current_user)]
