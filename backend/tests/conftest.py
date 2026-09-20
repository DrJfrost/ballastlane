"""Shared fixtures.

Two families of tests share this file:

* **unit** -- construct a use case with the fakes from ``tests.fakes``; no
  database, no HTTP, no event loop contention. Milliseconds.
* **integration** -- drive the real ASGI app against a real (SQLite)
  database through ``httpx``, so routing, validation, DI, SQL and the error
  envelope are all exercised together.

Each test gets its own in-memory database. Sharing one across the module is
faster but couples tests through leftover rows, which is how a suite starts
depending on execution order.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

# Set before any taskflow import so the module-level rate limiter and the
# cached settings are built with test values.
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "SECRET_KEY": "test-secret-key-that-is-long-enough-for-hs256-signing",
        # 4 is the bcrypt minimum; the real hasher stays in play (so its
        # behaviour is genuinely covered) without the 250 ms per call.
        "BCRYPT_ROUNDS": "4",
        "CELERY_ENABLED": "false",
        "RATE_LIMIT_ENABLED": "false",
        "RATE_LIMIT_STORAGE_URL": "memory://",
        "LOG_LEVEL": "WARNING",
        "LOG_JSON": "false",
        "DOCS_ENABLED": "true",
    }
)

from taskflow.application.ports.token_service import TokenType
from taskflow.domain.entities import Task, User
from taskflow.domain.enums import TaskPriority, TaskStatus
from taskflow.domain.value_objects import (
    Email,
    PersonName,
    TaskDescription,
    TaskTitle,
)
from taskflow.infrastructure.config.settings import Settings, get_settings
from taskflow.infrastructure.db.models import Base
from taskflow.infrastructure.services import FixedClock
from taskflow.main import create_app
from taskflow.presentation.dependencies.container import Container
from tests.fakes import (
    FakePasswordHasher,
    InMemoryTaskRepository,
    InMemoryUnitOfWork,
    InMemoryUserRepository,
    RecordingEventPublisher,
)

#: A fixed "now" for the whole suite. Every time-dependent assertion is
#: relative to it, so no test can flake at midnight or across a DST change.
NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)

DEMO_PASSWORD = "IntegrationPassw0rd!"


# --------------------------------------------------------------------- #
# Unit-test fixtures
# --------------------------------------------------------------------- #
@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
def hasher() -> FakePasswordHasher:
    return FakePasswordHasher()


@pytest.fixture
def publisher() -> RecordingEventPublisher:
    return RecordingEventPublisher()


@pytest.fixture
def users_repo() -> InMemoryUserRepository:
    return InMemoryUserRepository()


@pytest.fixture
def tasks_repo() -> InMemoryTaskRepository:
    return InMemoryTaskRepository()


@pytest.fixture
def uow(
    users_repo: InMemoryUserRepository, tasks_repo: InMemoryTaskRepository
) -> InMemoryUnitOfWork:
    return InMemoryUnitOfWork(users=users_repo, tasks=tasks_repo)


def make_user(
    *,
    email: str = "owner@taskflow.dev",
    full_name: str = "Owner Person",
    user_id: UUID | None = None,
    is_active: bool = True,
    hashed_password: str = "fake$secret",
    moment: datetime | None = None,
) -> User:
    user = User.register(
        email=Email(email),
        full_name=PersonName(full_name),
        hashed_password=hashed_password,
        now=moment or NOW,
        user_id=user_id or uuid4(),
    )
    if not is_active:
        user.deactivate(now=moment or NOW)
    return user


def make_task(
    *,
    owner_id: UUID,
    title: str = "A reasonable task title",
    description: str = "",
    status: TaskStatus = TaskStatus.TODO,
    priority: TaskPriority = TaskPriority.MEDIUM,
    assignee_id: UUID | None = None,
    due_date: datetime | None = None,
    completed_at: datetime | None = None,
    task_id: UUID | None = None,
    moment: datetime | None = None,
) -> Task:
    """Build a Task directly, bypassing the ``create`` factory.

    Used when a test needs a state the factory legitimately refuses to
    produce -- an already-completed task, or one whose deadline is in the
    past. Going through the factory and then mutating would be a longer way
    to express the same fixture.
    """
    moment = moment or NOW
    return Task(
        id=task_id or uuid4(),
        title=TaskTitle(title),
        description=TaskDescription(description),
        status=status,
        priority=priority,
        owner_id=owner_id,
        assignee_id=assignee_id,
        due_date=due_date,
        completed_at=completed_at if status is TaskStatus.DONE else None,
        created_at=moment,
        updated_at=moment,
    )


@pytest.fixture
def owner() -> User:
    return make_user(
        email="owner@taskflow.dev",
        full_name="Ada Lovelace",
        user_id=UUID("aaaaaaaa-0000-4000-8000-000000000001"),
    )


@pytest.fixture
def teammate() -> User:
    return make_user(
        email="teammate@taskflow.dev",
        full_name="Grace Hopper",
        user_id=UUID("aaaaaaaa-0000-4000-8000-000000000002"),
    )


@pytest.fixture
def outsider() -> User:
    return make_user(
        email="outsider@taskflow.dev",
        full_name="Alan Turing",
        user_id=UUID("aaaaaaaa-0000-4000-8000-000000000003"),
    )


@pytest.fixture
async def populated_uow(
    uow: InMemoryUnitOfWork, owner: User, teammate: User, outsider: User
) -> InMemoryUnitOfWork:
    for user in (owner, teammate, outsider):
        await uow.users.add(user)
    return uow


# --------------------------------------------------------------------- #
# Integration fixtures
# --------------------------------------------------------------------- #
@pytest.fixture
def settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
async def container(settings: Settings) -> AsyncIterator[Container]:
    """A real container on a private in-memory database."""
    instance = Container(settings)
    async with instance.engine.begin() as connection:
        # ``create_all`` rather than ``alembic upgrade head``: the schema is
        # asserted against the models here, and a dedicated test runs the
        # migrations so the two cannot drift unnoticed.
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield instance
    finally:
        await instance.dispose()


@pytest.fixture
async def client(container: Container, settings: Settings) -> AsyncIterator[AsyncClient]:
    """An HTTP client bound to the real app, wired to the test container.

    The container is injected rather than letting the lifespan build one, so
    the test keeps a handle on the same engine and event publisher the app is
    using and can assert against them.
    """
    app = create_app(settings)
    app.state.container = container
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http


async def register_and_login(
    client: AsyncClient,
    *,
    email: str,
    full_name: str = "Test Person",
    password: str = DEMO_PASSWORD,
) -> dict[str, str]:
    """Create an account and return ready-to-use auth headers."""
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "full_name": full_name, "password": password},
    )
    assert response.status_code == 201, response.text
    user_id = response.json()["id"]

    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return {
        "Authorization": f"Bearer {body['access_token']}",
        "X-Test-User-Id": user_id,
        "X-Test-Refresh": body["refresh_token"],
    }


@pytest.fixture
async def alice(client: AsyncClient) -> dict[str, str]:
    return await register_and_login(client, email="alice@taskflow.dev", full_name="Alice Owner")


@pytest.fixture
async def bob(client: AsyncClient) -> dict[str, str]:
    return await register_and_login(client, email="bob@taskflow.dev", full_name="Bob Assignee")


@pytest.fixture
async def carol(client: AsyncClient) -> dict[str, str]:
    return await register_and_login(
        client, email="carol@taskflow.dev", full_name="Carol Outsider"
    )


@pytest.fixture
def future_date() -> str:
    """An ISO deadline far enough ahead to stay valid as the suite ages."""
    return (datetime.now(UTC) + timedelta(days=30)).isoformat().replace("+00:00", "Z")


def auth(headers: dict[str, str]) -> dict[str, str]:
    """Strip the test-only bookkeeping headers before sending a request."""
    return {"Authorization": headers["Authorization"]}


def user_id_of(headers: dict[str, str]) -> str:
    return headers["X-Test-User-Id"]


__all__ = [
    "DEMO_PASSWORD",
    "NOW",
    "TokenType",
    "auth",
    "make_task",
    "make_user",
    "register_and_login",
    "user_id_of",
]
