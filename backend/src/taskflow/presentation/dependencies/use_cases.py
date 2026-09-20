"""FastAPI providers for every use case.

Each provider is three lines of wiring. That repetition is deliberate and
preferable to a magic auto-wiring container: the graph is explicit, a missing
dependency is a type error rather than a runtime KeyError, and ``Depends``
overrides in tests work per use case.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from taskflow.application.use_cases.auth import (
    AuthenticateUser,
    RefreshAccessToken,
    RegisterUser,
    ResolveCurrentUser,
)
from taskflow.application.use_cases.tasks import (
    AssignTask,
    CompleteTask,
    CreateTask,
    DeleteTask,
    GetTask,
    GetTaskStats,
    ListTasks,
    ReopenTask,
    UpdateTask,
)
from taskflow.application.use_cases.users import ListUsers
from taskflow.presentation.dependencies.container import ContainerDep


# ----------------------------------------------------------------- auth
def provide_register_user(container: ContainerDep) -> RegisterUser:
    return RegisterUser(
        uow=container.unit_of_work(),
        hasher=container.password_hasher,
        clock=container.clock,
    )


def provide_authenticate_user(container: ContainerDep) -> AuthenticateUser:
    return AuthenticateUser(
        uow=container.unit_of_work(),
        hasher=container.password_hasher,
        tokens=container.token_service,
        clock=container.clock,
    )


def provide_refresh_access_token(container: ContainerDep) -> RefreshAccessToken:
    return RefreshAccessToken(uow=container.unit_of_work(), tokens=container.token_service)


def provide_resolve_current_user(container: ContainerDep) -> ResolveCurrentUser:
    return ResolveCurrentUser(uow=container.unit_of_work(), tokens=container.token_service)


# ---------------------------------------------------------------- tasks
def provide_create_task(container: ContainerDep) -> CreateTask:
    return CreateTask(
        uow=container.unit_of_work(),
        clock=container.clock,
        publisher=container.event_publisher,
    )


def provide_get_task(container: ContainerDep) -> GetTask:
    return GetTask(uow=container.unit_of_work(), clock=container.clock)


def provide_list_tasks(container: ContainerDep) -> ListTasks:
    return ListTasks(uow=container.unit_of_work(), clock=container.clock)


def provide_update_task(container: ContainerDep) -> UpdateTask:
    return UpdateTask(
        uow=container.unit_of_work(),
        clock=container.clock,
        publisher=container.event_publisher,
    )


def provide_complete_task(container: ContainerDep) -> CompleteTask:
    return CompleteTask(
        uow=container.unit_of_work(),
        clock=container.clock,
        publisher=container.event_publisher,
    )


def provide_reopen_task(container: ContainerDep) -> ReopenTask:
    return ReopenTask(
        uow=container.unit_of_work(),
        clock=container.clock,
        publisher=container.event_publisher,
    )


def provide_assign_task(container: ContainerDep) -> AssignTask:
    return AssignTask(
        uow=container.unit_of_work(),
        clock=container.clock,
        publisher=container.event_publisher,
    )


def provide_delete_task(container: ContainerDep) -> DeleteTask:
    return DeleteTask(
        uow=container.unit_of_work(),
        clock=container.clock,
        publisher=container.event_publisher,
    )


def provide_get_task_stats(container: ContainerDep) -> GetTaskStats:
    return GetTaskStats(uow=container.unit_of_work(), clock=container.clock)


# ---------------------------------------------------------------- users
def provide_list_users(container: ContainerDep) -> ListUsers:
    return ListUsers(uow=container.unit_of_work())


# Aliases so routers read as ``use_case: CreateTaskDep`` rather than carrying
# a ``Depends(...)`` in every signature.
RegisterUserDep = Annotated[RegisterUser, Depends(provide_register_user)]
AuthenticateUserDep = Annotated[AuthenticateUser, Depends(provide_authenticate_user)]
RefreshAccessTokenDep = Annotated[RefreshAccessToken, Depends(provide_refresh_access_token)]
ResolveCurrentUserDep = Annotated[ResolveCurrentUser, Depends(provide_resolve_current_user)]
CreateTaskDep = Annotated[CreateTask, Depends(provide_create_task)]
GetTaskDep = Annotated[GetTask, Depends(provide_get_task)]
ListTasksDep = Annotated[ListTasks, Depends(provide_list_tasks)]
UpdateTaskDep = Annotated[UpdateTask, Depends(provide_update_task)]
CompleteTaskDep = Annotated[CompleteTask, Depends(provide_complete_task)]
ReopenTaskDep = Annotated[ReopenTask, Depends(provide_reopen_task)]
AssignTaskDep = Annotated[AssignTask, Depends(provide_assign_task)]
DeleteTaskDep = Annotated[DeleteTask, Depends(provide_delete_task)]
GetTaskStatsDep = Annotated[GetTaskStats, Depends(provide_get_task_stats)]
ListUsersDep = Annotated[ListUsers, Depends(provide_list_users)]
