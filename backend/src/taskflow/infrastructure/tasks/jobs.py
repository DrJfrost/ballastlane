"""Background jobs.

These are the *only* place where "send a notification" happens. Keeping them
out of the request path means a slow or unavailable mail provider cannot turn
a 201 into a timeout, and a failed send can be retried without the user
resubmitting anything.

In a real deployment the ``_deliver`` helper would call an email or push
provider. Here it logs a structured record, which keeps the exercise
self-contained while leaving one obvious seam to replace.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from uuid import UUID

from celery import shared_task
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from taskflow.domain.enums import TaskStatus
from taskflow.infrastructure.config.settings import get_settings
from taskflow.infrastructure.db.models import TaskModel, UserModel

logger = logging.getLogger("taskflow.jobs")


@shared_task(
    name="taskflow.notify_task_assigned",
    bind=True,
    max_retries=5,
    # Exponential backoff with jitter: a provider outage otherwise gets a
    # synchronised retry storm from every worker at the same instant.
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    autoretry_for=(Exception,),
)
def notify_task_assigned(
    self: Any,
    *,
    task_id: str,
    task_title: str,
    assignee_id: str,
    assigned_by: str,
) -> dict[str, str]:
    """Tell someone a task landed on their plate."""
    with _session() as session:
        assignee = session.get(UserModel, _uuid(assignee_id))
        actor = session.get(UserModel, _uuid(assigned_by))

    if assignee is None:
        # The user was deleted between the commit and this job running.
        # Nothing to deliver, and retrying will never help -- so do not.
        logger.warning("assignee_missing", extra={"assignee_id": assignee_id})
        return {"status": "skipped", "reason": "assignee_missing"}

    return _deliver(
        channel="task_assigned",
        to=assignee.email,
        subject=f"New task assigned: {task_title}",
        body=(
            f"{actor.full_name if actor else 'Someone'} assigned you the task "
            f"'{task_title}'. Open TaskFlow to get started."
        ),
        context={"task_id": task_id},
    )


@shared_task(
    name="taskflow.notify_task_completed",
    bind=True,
    max_retries=5,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    autoretry_for=(Exception,),
)
def notify_task_completed(
    self: Any,
    *,
    task_id: str,
    task_title: str,
    completed_by: str,
    owner_id: str,
    was_overdue: bool,
) -> dict[str, str]:
    """Tell the owner their task is done -- unless they did it themselves."""
    if completed_by == owner_id:
        return {"status": "skipped", "reason": "actor_is_owner"}

    with _session() as session:
        owner = session.get(UserModel, _uuid(owner_id))
        actor = session.get(UserModel, _uuid(completed_by))

    if owner is None:
        logger.warning("owner_missing", extra={"owner_id": owner_id})
        return {"status": "skipped", "reason": "owner_missing"}

    suffix = " (after the due date)" if was_overdue else ""
    return _deliver(
        channel="task_completed",
        to=owner.email,
        subject=f"Task completed: {task_title}",
        body=(f"{actor.full_name if actor else 'Someone'} completed '{task_title}'{suffix}."),
        context={"task_id": task_id},
    )


@shared_task(name="taskflow.notify_due_date_changed")
def notify_due_date_changed(
    *,
    task_id: str,
    new_due_date: str | None,
    changed_by: str,
) -> dict[str, str]:
    """Tell the assignee their deadline moved."""
    with _session() as session:
        task = session.get(TaskModel, _uuid(task_id))
        if task is None or task.assignee_id is None:
            return {"status": "skipped", "reason": "no_assignee"}
        if str(task.assignee_id) == changed_by:
            return {"status": "skipped", "reason": "actor_is_assignee"}
        assignee = session.get(UserModel, task.assignee_id)
        title = task.title

    if assignee is None:
        return {"status": "skipped", "reason": "assignee_missing"}

    when = new_due_date or "no deadline"
    return _deliver(
        channel="due_date_changed",
        to=assignee.email,
        subject=f"Deadline moved: {title}",
        body=f"The due date for '{title}' is now {when}.",
        context={"task_id": task_id},
    )


@shared_task(name="taskflow.scan_overdue_tasks")
def scan_overdue_tasks() -> dict[str, int]:
    """Daily digest of work that has slipped.

    Runs on Celery beat. The query is done in SQL with a join, not by
    loading every task and filtering in Python, so the job cost is
    proportional to the number of *overdue* tasks rather than to the size of
    the table.
    """
    now = datetime.now(UTC)

    with _session() as session:
        rows = session.execute(
            select(TaskModel, UserModel)
            .join(UserModel, UserModel.id == TaskModel.owner_id)
            .where(
                TaskModel.due_date.is_not(None),
                TaskModel.due_date < now,
                TaskModel.status.in_([s.value for s in TaskStatus if s.is_open]),
            )
            .order_by(TaskModel.due_date.asc())
        ).all()

    # One digest per person instead of one email per task: a user with 40
    # overdue tasks should get one message, not 40.
    per_owner: dict[str, list[str]] = {}
    for task, owner in rows:
        per_owner.setdefault(owner.email, []).append(task.title)

    for email, titles in per_owner.items():
        _deliver(
            channel="overdue_digest",
            to=email,
            subject=f"You have {len(titles)} overdue task(s)",
            body="\n".join(f"- {title}" for title in titles),
            context={"count": str(len(titles))},
        )

    logger.info(
        "overdue_scan_complete",
        extra={"overdue_tasks": len(rows), "recipients": len(per_owner)},
    )
    return {"overdue_tasks": len(rows), "recipients": len(per_owner)}


# --------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def _engine() -> Engine:
    """One synchronous engine per worker process.

    Cached deliberately: building an ``Engine`` per task creates a fresh
    connection pool each time, so a busy worker accumulates idle connections
    until PostgreSQL refuses new ones with "too many clients".

    It is synchronous because Celery workers are threads or processes, not an
    event loop -- reusing the async engine would mean an ``asyncio.run`` per
    task, and a pool bound to a loop that no longer exists.
    """
    settings = get_settings()
    # SQLite picks a pool class that rejects sizing arguments, so they are
    # only passed for real server backends.
    pool_options: dict[str, object] = (
        {} if settings.is_sqlite else {"pool_size": 2, "max_overflow": 3}
    )
    return create_engine(
        settings.sync_database_url,
        pool_pre_ping=True,
        future=True,
        **pool_options,
    )


def _session() -> Session:
    return Session(_engine(), expire_on_commit=False)


def _uuid(value: str) -> UUID:
    return UUID(value)


def _deliver(
    *,
    channel: str,
    to: str,
    subject: str,
    body: str,
    context: dict[str, str] | None = None,
) -> dict[str, str]:
    """The single seam where a real provider would be plugged in."""
    logger.info(
        "notification_sent",
        extra={
            "channel": channel,
            "recipient": to,
            "subject": subject,
            "body_preview": body[:120],
            **(context or {}),
        },
    )
    return {"status": "sent", "channel": channel, "recipient": to}
