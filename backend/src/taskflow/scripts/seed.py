"""Seed the database with demo users and tasks.

Run with ``python -m taskflow.scripts.seed`` (or ``make seed``). Safe to run
repeatedly: it upserts by a fixed set of UUIDs, so a second run refreshes the
data instead of piling up duplicates. That matters for a demo -- the reviewer
should be able to reset to a known state without dropping the database.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select

from taskflow.domain.entities import Task, User
from taskflow.domain.enums import TaskPriority, TaskStatus
from taskflow.domain.value_objects import Email, PersonName, TaskDescription, TaskTitle
from taskflow.infrastructure.config.settings import get_settings
from taskflow.infrastructure.db.engine import create_engine, create_session_factory
from taskflow.infrastructure.db.mappers import task_to_model, user_to_model
from taskflow.infrastructure.db.models import Base, TaskModel, UserModel
from taskflow.infrastructure.security import BcryptPasswordHasher

logger = logging.getLogger("taskflow.seed")

# Fixed ids keep the seed idempotent and make the demo credentials stable
# across resets, which is what the README documents.
ADA = UUID("0f3f0a4a-0000-4000-8000-000000000001")
GRACE = UUID("0f3f0a4a-0000-4000-8000-000000000002")
ALAN = UUID("0f3f0a4a-0000-4000-8000-000000000003")
MARGARET = UUID("0f3f0a4a-0000-4000-8000-000000000004")

PEOPLE = [
    (ADA, "ada@taskflow.dev", "Ada Lovelace"),
    (GRACE, "grace@taskflow.dev", "Grace Hopper"),
    (ALAN, "alan@taskflow.dev", "Alan Turing"),
    (MARGARET, "margaret@taskflow.dev", "Margaret Hamilton"),
]


def _task_blueprints() -> list[dict[str, Any]]:
    """A dataset that exercises every filter the UI offers.

    Chosen on purpose: overdue items, items due today and next week, undated
    items, one of each status and priority, tasks owned by the demo user and
    tasks merely assigned to them. A seed of twenty identical rows proves
    nothing about pagination or filtering.
    """
    return [
        # --- overdue, open: proves the overdue filter and the red badge ---
        {
            "id": UUID("0f3f0a4a-1111-4000-8000-000000000001"),
            "title": "Rotate the production database credentials",
            "description": "Quarterly rotation. Coordinate with the platform team.",
            "status": TaskStatus.IN_PROGRESS,
            "priority": TaskPriority.URGENT,
            "owner_id": ADA,
            "assignee_id": ADA,
            "due_offset": timedelta(days=-3),
        },
        {
            "id": UUID("0f3f0a4a-1111-4000-8000-000000000002"),
            "title": "Reply to the security questionnaire",
            "description": "Vendor review, 40 questions. Draft is in the shared drive.",
            "status": TaskStatus.TODO,
            "priority": TaskPriority.HIGH,
            "owner_id": GRACE,
            "assignee_id": ADA,
            "due_offset": timedelta(days=-1, hours=-6),
        },
        # --- due soon ---
        {
            "id": UUID("0f3f0a4a-1111-4000-8000-000000000003"),
            "title": "Prepare the Q4 architecture review deck",
            "description": "Focus on the ingestion pipeline and the migration plan.",
            "status": TaskStatus.IN_PROGRESS,
            "priority": TaskPriority.HIGH,
            "owner_id": ADA,
            "assignee_id": GRACE,
            "due_offset": timedelta(days=2),
        },
        {
            "id": UUID("0f3f0a4a-1111-4000-8000-000000000004"),
            "title": "Add pagination to the audit log endpoint",
            "description": "Currently returns every row; it times out past 50k entries.",
            "status": TaskStatus.TODO,
            "priority": TaskPriority.MEDIUM,
            "owner_id": ADA,
            "assignee_id": ALAN,
            "due_offset": timedelta(days=5),
        },
        {
            "id": UUID("0f3f0a4a-1111-4000-8000-000000000005"),
            "title": "Write the onboarding runbook",
            "description": "Everything a new joiner needs in their first week.",
            "status": TaskStatus.TODO,
            "priority": TaskPriority.LOW,
            "owner_id": MARGARET,
            "assignee_id": ADA,
            "due_offset": timedelta(days=12),
        },
        # --- undated: proves has_due_date=false and null-sorting ---
        {
            "id": UUID("0f3f0a4a-1111-4000-8000-000000000006"),
            "title": "Investigate flaky integration test on CI",
            "description": "Fails roughly one run in twenty; suspect a timing assumption.",
            "status": TaskStatus.TODO,
            "priority": TaskPriority.MEDIUM,
            "owner_id": ADA,
            "assignee_id": None,
            "due_offset": None,
        },
        {
            "id": UUID("0f3f0a4a-1111-4000-8000-000000000007"),
            "title": "Evaluate replacing Celery with arq",
            "description": "Spike only. Compare operational cost and retry semantics.",
            "status": TaskStatus.TODO,
            "priority": TaskPriority.LOW,
            "owner_id": ADA,
            "assignee_id": None,
            "due_offset": None,
        },
        # --- completed ---
        {
            "id": UUID("0f3f0a4a-1111-4000-8000-000000000008"),
            "title": "Ship JWT refresh-token rotation",
            "description": "Access tokens now live 15 minutes.",
            "status": TaskStatus.DONE,
            "priority": TaskPriority.HIGH,
            "owner_id": ADA,
            "assignee_id": ADA,
            "due_offset": timedelta(days=-10),
            "completed_offset": timedelta(days=-11),
        },
        {
            "id": UUID("0f3f0a4a-1111-4000-8000-000000000009"),
            "title": "Document the deployment pipeline",
            "description": "Added the rollback procedure that was missing.",
            "status": TaskStatus.DONE,
            "priority": TaskPriority.MEDIUM,
            "owner_id": GRACE,
            "assignee_id": ADA,
            "due_offset": timedelta(days=-7),
            "completed_offset": timedelta(days=-8),
        },
        # --- cancelled ---
        {
            "id": UUID("0f3f0a4a-1111-4000-8000-00000000000a"),
            "title": "Migrate the legacy reporting job to Spark",
            "description": "Cancelled: the source system is being retired instead.",
            "status": TaskStatus.CANCELLED,
            "priority": TaskPriority.LOW,
            "owner_id": ADA,
            "assignee_id": None,
            "due_offset": timedelta(days=30),
        },
        # --- a second page of filler, so pagination is visible ---
        *[
            {
                "id": UUID(f"0f3f0a4a-2222-4000-8000-{index:012x}"),
                "title": f"Review pull request #{1200 + index}",
                "description": "Routine review from the backlog rotation.",
                "status": TaskStatus.TODO if index % 3 else TaskStatus.IN_PROGRESS,
                "priority": [
                    TaskPriority.LOW,
                    TaskPriority.MEDIUM,
                    TaskPriority.HIGH,
                ][index % 3],
                "owner_id": ADA,
                "assignee_id": [ADA, GRACE, ALAN, MARGARET][index % 4],
                "due_offset": timedelta(days=index),
            }
            for index in range(1, 16)
        ],
    ]


async def seed() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    hasher = BcryptPasswordHasher(rounds=settings.bcrypt_rounds)
    # A single timestamp for the whole run, so relative offsets stay
    # consistent and the dataset is reproducible.
    now = datetime.now(UTC)
    password = settings.seed_password.get_secret_value()

    async with engine.begin() as connection:
        # Convenient for SQLite demos; real deployments run Alembic instead
        # and this is a no-op because the tables already exist.
        await connection.run_sync(Base.metadata.create_all)

    seeded_user_ids = [person[0] for person in PEOPLE]
    blueprints = _task_blueprints()
    seeded_task_ids = [blueprint["id"] for blueprint in blueprints]

    async with session_factory() as session:
        # Remove only what this script owns. A blanket ``DELETE FROM tasks``
        # would wipe anything the reviewer created while exploring.
        await session.execute(delete(TaskModel).where(TaskModel.id.in_(seeded_task_ids)))
        await session.execute(delete(UserModel).where(UserModel.id.in_(seeded_user_ids)))
        await session.flush()

        hashed = hasher.hash(password)
        for user_id, email, full_name in PEOPLE:
            user = User.register(
                email=Email(email),
                full_name=PersonName(full_name),
                hashed_password=hashed,
                now=now,
                user_id=user_id,
            )
            session.add(user_to_model(user))
        await session.flush()

        for blueprint in blueprints:
            due_offset = blueprint.get("due_offset")
            task = Task(
                id=blueprint["id"],
                title=TaskTitle(blueprint["title"]),
                description=TaskDescription(blueprint["description"]),
                status=blueprint["status"],
                priority=blueprint["priority"],
                owner_id=blueprint["owner_id"],
                assignee_id=blueprint["assignee_id"],
                due_date=now + due_offset if due_offset is not None else None,
                # The DB check constraint requires completed_at exactly when
                # status is done, so it is derived rather than hand-set.
                completed_at=(
                    now + blueprint.get("completed_offset", timedelta())
                    if blueprint["status"] is TaskStatus.DONE
                    else None
                ),
                created_at=now - timedelta(days=20),
                updated_at=now,
            )
            session.add(task_to_model(task))

        await session.commit()

        total = (await session.execute(select(TaskModel.id))).scalars().all()

    await engine.dispose()

    print("Seed complete.")
    print(f"  users: {len(PEOPLE)}   tasks in database: {len(total)}")
    print("  demo credentials:")
    for _, email, full_name in PEOPLE:
        print(f"    {email:28} {password:20} ({full_name})")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(seed())


if __name__ == "__main__":
    main()
