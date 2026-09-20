"""Task endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request, Response, status

from taskflow.application.dto import (
    AssignTaskCommand,
    CompleteTaskCommand,
    DeleteTaskCommand,
    GetTaskQuery,
    ListTasksQuery,
    ReopenTaskCommand,
    TaskStatsQuery,
)
from taskflow.presentation.dependencies.auth import CurrentUser
from taskflow.presentation.dependencies.query_params import PaginationDep, TaskFilterDep
from taskflow.presentation.dependencies.use_cases import (
    AssignTaskDep,
    CompleteTaskDep,
    CreateTaskDep,
    DeleteTaskDep,
    GetTaskDep,
    GetTaskStatsDep,
    ListTasksDep,
    ReopenTaskDep,
    UpdateTaskDep,
)
from taskflow.presentation.rate_limit import limit
from taskflow.presentation.schemas.common import PaginatedResponse, ProblemDetail
from taskflow.presentation.schemas.tasks import (
    AssignTaskRequest,
    CreateTaskRequest,
    TaskResponse,
    TaskStatsResponse,
    UpdateTaskRequest,
)

router = APIRouter(prefix="/tasks", tags=["Tasks"])

#: Declared once so the description appears identically on every route.
TaskId = Annotated[UUID, Path(description="The task identifier (UUID).")]

#: Endpoints carrying a per-route limit must accept ``response: Response``:
#: slowapi writes the ``X-RateLimit-*`` headers into it, and refuses to run
#: without it when ``headers_enabled`` is on.

_COMMON_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ProblemDetail, "description": "Missing or invalid token."},
    404: {"model": ProblemDetail, "description": "Task not found or not visible to you."},
    422: {"model": ProblemDetail, "description": "Validation failed."},
    429: {"model": ProblemDetail, "description": "Rate limit exceeded."},
}
_WRITE_ERRORS: dict[int | str, dict[str, object]] = {
    **_COMMON_ERRORS,
    403: {"model": ProblemDetail, "description": "You are not allowed to do this."},
    409: {"model": ProblemDetail, "description": "Illegal state transition."},
}


@router.get(
    "",
    response_model=PaginatedResponse[TaskResponse],
    summary="List tasks",
    description=(
        "Returns the tasks you own or are assigned to, newest first by default.\n\n"
        "**Filtering** -- combine any of `status`, `priority`, `due_before`, "
        "`due_after`, `has_due_date`, `overdue_only`, `assignee_id`, `owner_id`, "
        "`assigned_to_me`, `created_by_me`, `unassigned_only`, `search`.\n\n"
        "**Pagination** -- `page` and `page_size`; the `meta` object carries "
        "`total`, `total_pages`, `has_next` and `has_previous`."
    ),
    responses=_COMMON_ERRORS,
)
async def list_tasks(
    current_user: CurrentUser,
    use_case: ListTasksDep,
    pagination: PaginationDep,
    filters: TaskFilterDep,
) -> PaginatedResponse[TaskResponse]:
    page = await use_case.execute(
        ListTasksQuery(
            actor_id=current_user.id,
            pagination=pagination.to_pagination(),
            statuses=filters.statuses,
            priorities=filters.priorities,
            due_before=filters.due_before,
            due_after=filters.due_after,
            has_due_date=filters.has_due_date,
            overdue_only=filters.overdue_only,
            assignee_id=filters.assignee_id,
            owner_id=filters.owner_id,
            assigned_to_me=filters.assigned_to_me,
            created_by_me=filters.created_by_me,
            unassigned_only=filters.unassigned_only,
            search=filters.search,
            sort_by=filters.sort_by,
            sort_dir=filters.sort_dir,
        )
    )
    return PaginatedResponse[TaskResponse].from_page(page, TaskResponse.from_view)


@router.get(
    "/stats",
    response_model=TaskStatsResponse,
    summary="Counters for the dashboard",
    responses=_COMMON_ERRORS,
)
async def task_stats(
    current_user: CurrentUser,
    use_case: GetTaskStatsDep,
) -> TaskStatsResponse:
    # Declared *before* ``/{task_id}`` on purpose: FastAPI matches routes in
    # declaration order, so a later literal path would be swallowed by the
    # UUID parameter and answered with a 422.
    view = await use_case.execute(TaskStatsQuery(actor_id=current_user.id))
    return TaskStatsResponse.from_view(view)


@router.post(
    "",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a task",
    responses=_WRITE_ERRORS,
)
@limit("write")
async def create_task(
    request: Request,
    response: Response,
    payload: CreateTaskRequest,
    current_user: CurrentUser,
    use_case: CreateTaskDep,
) -> TaskResponse:
    view = await use_case.execute(payload.to_command(current_user.id))
    return TaskResponse.from_view(view)


@router.get(
    "/{task_id}",
    response_model=TaskResponse,
    summary="Read one task",
    responses=_COMMON_ERRORS,
)
async def get_task(
    current_user: CurrentUser,
    use_case: GetTaskDep,
    task_id: TaskId,
) -> TaskResponse:
    view = await use_case.execute(GetTaskQuery(actor_id=current_user.id, task_id=task_id))
    return TaskResponse.from_view(view)


@router.patch(
    "/{task_id}",
    response_model=TaskResponse,
    summary="Partially update a task",
    description=(
        "Only the fields present in the body are changed. `due_date` and "
        "`assignee_id` accept `null` to clear them; omitting a field leaves it "
        "untouched."
    ),
    responses=_WRITE_ERRORS,
)
@limit("write")
async def update_task(
    request: Request,
    response: Response,
    payload: UpdateTaskRequest,
    current_user: CurrentUser,
    use_case: UpdateTaskDep,
    task_id: TaskId,
) -> TaskResponse:
    view = await use_case.execute(payload.to_command(current_user.id, task_id))
    return TaskResponse.from_view(view)


@router.post(
    "/{task_id}/complete",
    response_model=TaskResponse,
    summary="Mark a task as completed",
    description="Allowed for the owner and the assignee. Idempotency is not "
    "implied: completing an already-completed task returns 409.",
    responses=_WRITE_ERRORS,
)
@limit("write")
async def complete_task(
    request: Request,
    response: Response,
    current_user: CurrentUser,
    use_case: CompleteTaskDep,
    task_id: TaskId,
) -> TaskResponse:
    view = await use_case.execute(
        CompleteTaskCommand(actor_id=current_user.id, task_id=task_id)
    )
    return TaskResponse.from_view(view)


@router.post(
    "/{task_id}/reopen",
    response_model=TaskResponse,
    summary="Reopen a closed task",
    responses=_WRITE_ERRORS,
)
@limit("write")
async def reopen_task(
    request: Request,
    response: Response,
    current_user: CurrentUser,
    use_case: ReopenTaskDep,
    task_id: TaskId,
) -> TaskResponse:
    view = await use_case.execute(ReopenTaskCommand(actor_id=current_user.id, task_id=task_id))
    return TaskResponse.from_view(view)


@router.put(
    "/{task_id}/assignee",
    response_model=TaskResponse,
    summary="Assign or unassign a task",
    description='Owner only. Send `{"assignee_id": null}` to unassign.',
    responses=_WRITE_ERRORS,
)
@limit("write")
async def assign_task(
    request: Request,
    response: Response,
    payload: AssignTaskRequest,
    current_user: CurrentUser,
    use_case: AssignTaskDep,
    task_id: TaskId,
) -> TaskResponse:
    view = await use_case.execute(
        AssignTaskCommand(
            actor_id=current_user.id,
            task_id=task_id,
            assignee_id=payload.assignee_id,
        )
    )
    return TaskResponse.from_view(view)


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a task",
    description="Owner only.",
    responses=_WRITE_ERRORS,
)
@limit("write")
async def delete_task(
    request: Request,
    response: Response,
    current_user: CurrentUser,
    use_case: DeleteTaskDep,
    task_id: TaskId,
) -> Response:
    await use_case.execute(DeleteTaskCommand(actor_id=current_user.id, task_id=task_id))
    # 204 must carry no body; returning the model would emit ``null`` and
    # make strict clients choke on a response that should be empty.
    return Response(status_code=status.HTTP_204_NO_CONTENT)
