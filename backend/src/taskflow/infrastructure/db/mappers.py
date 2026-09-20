"""Explicit translation between ORM rows and domain aggregates.

This is the seam that lets the domain stay persistence-ignorant. It is
intentionally boring, one-way-per-function code with no cleverness, because
it is the one place where a mistake silently corrupts data.
"""

from __future__ import annotations

from taskflow.domain.entities import Task, User
from taskflow.domain.enums import TaskPriority, TaskStatus
from taskflow.domain.value_objects import Email, PersonName, TaskDescription, TaskTitle
from taskflow.infrastructure.db.models import TaskModel, UserModel


def user_to_entity(row: UserModel) -> User:
    """Rehydrate a :class:`User` from a row.

    Value objects are constructed via ``__new__``-free normal calls, so data
    that was written before a validation rule existed would raise here rather
    than flow silently into the domain. That is the desired behaviour: a
    loud failure on load beats a corrupt aggregate.
    """
    return User(
        id=row.id,
        email=Email(row.email),
        full_name=PersonName(row.full_name),
        hashed_password=row.hashed_password,
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def user_to_model(user: User) -> UserModel:
    return UserModel(
        id=user.id,
        email=user.email.value,
        full_name=user.full_name.value,
        hashed_password=user.hashed_password,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def user_values(user: User) -> dict[str, object]:
    """Column values for an ``UPDATE`` (primary key excluded)."""
    return {
        "email": user.email.value,
        "full_name": user.full_name.value,
        "hashed_password": user.hashed_password,
        "is_active": user.is_active,
        "updated_at": user.updated_at,
    }


def task_to_entity(row: TaskModel) -> Task:
    return Task(
        id=row.id,
        title=TaskTitle(row.title),
        description=TaskDescription(row.description),
        status=TaskStatus(row.status),
        priority=TaskPriority(row.priority),
        owner_id=row.owner_id,
        assignee_id=row.assignee_id,
        due_date=row.due_date,
        completed_at=row.completed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def task_to_model(task: Task) -> TaskModel:
    return TaskModel(
        id=task.id,
        title=task.title.value,
        description=task.description.value,
        status=task.status.value,
        priority=task.priority.value,
        owner_id=task.owner_id,
        assignee_id=task.assignee_id,
        due_date=task.due_date,
        completed_at=task.completed_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def task_values(task: Task) -> dict[str, object]:
    """Column values for an ``UPDATE`` (primary key and ``created_at`` excluded)."""
    return {
        "title": task.title.value,
        "description": task.description.value,
        "status": task.status.value,
        "priority": task.priority.value,
        "owner_id": task.owner_id,
        "assignee_id": task.assignee_id,
        "due_date": task.due_date,
        "completed_at": task.completed_at,
        "updated_at": task.updated_at,
    }
