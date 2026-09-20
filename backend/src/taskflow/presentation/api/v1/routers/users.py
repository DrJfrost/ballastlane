"""User directory endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from taskflow.application.dto import ListUsersQuery
from taskflow.presentation.dependencies.auth import CurrentUser
from taskflow.presentation.dependencies.query_params import PaginationDep
from taskflow.presentation.dependencies.use_cases import ListUsersDep
from taskflow.presentation.schemas.auth import UserSummaryResponse
from taskflow.presentation.schemas.common import PaginatedResponse, ProblemDetail

router = APIRouter(prefix="/users", tags=["Users"])


@router.get(
    "",
    response_model=PaginatedResponse[UserSummaryResponse],
    summary="List teammates",
    description=(
        "Paged directory used by the assignee picker. Requires authentication "
        "and returns summaries only -- no password hashes, no internal flags."
    ),
    responses={
        401: {"model": ProblemDetail, "description": "Missing or invalid token."},
        429: {"model": ProblemDetail, "description": "Rate limit exceeded."},
    },
)
async def list_users(
    current_user: CurrentUser,
    use_case: ListUsersDep,
    pagination: PaginationDep,
    search: Annotated[
        str | None,
        Query(max_length=120, description="Match on name or email."),
    ] = None,
    active_only: Annotated[bool, Query(description="Exclude deactivated accounts.")] = True,
) -> PaginatedResponse[UserSummaryResponse]:
    page = await use_case.execute(
        ListUsersQuery(
            actor_id=current_user.id,
            pagination=pagination.to_pagination(),
            search=search.strip() if search and search.strip() else None,
            active_only=active_only,
        )
    )
    return PaginatedResponse[UserSummaryResponse].from_page(
        page,
        lambda view: UserSummaryResponse(
            id=view.id,
            email=view.email,
            full_name=view.full_name,
            initials=view.initials,
        ),
    )
