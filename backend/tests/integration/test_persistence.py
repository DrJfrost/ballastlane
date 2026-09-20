"""Persistence concerns: migrations, constraints, timezone handling, health."""

from __future__ import annotations

import logging
import pathlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, insert, inspect, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.ext.asyncio import AsyncSession

from taskflow.domain.enums import TaskPriority, TaskStatus
from taskflow.domain.errors import AlreadyExistsError
from taskflow.domain.repositories import Pagination, TaskFilter, UserFilter
from taskflow.domain.value_objects import Email, TaskTitle
from taskflow.infrastructure.db.mappers import (
    task_to_entity,
    task_to_model,
    user_to_entity,
    user_to_model,
)
from taskflow.infrastructure.db.models import Base, TaskModel, UserModel
from taskflow.infrastructure.db.repositories import (
    SqlAlchemyTaskRepository,
    SqlAlchemyUserRepository,
)
from taskflow.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from tests.conftest import NOW, make_task, make_user

pytestmark = [pytest.mark.integration]

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[2]


class TestMigrations:
    def test_migrations_produce_the_same_schema_as_the_models(
        self, tmp_path: pathlib.Path
    ) -> None:
        """The check that stops schema drift.

        The suite creates tables with ``Base.metadata.create_all`` for speed,
        while production runs Alembic. Without comparing the two, a model
        change without a migration passes every test and then fails on
        deploy.
        """
        migrated = tmp_path / "migrated.db"
        config = Config(str(BACKEND_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
        config.set_main_option("sqlalchemy.url", f"sqlite:///{migrated}")
        command.upgrade(config, "head")

        expected = tmp_path / "expected.db"
        engine = create_engine(f"sqlite:///{expected}")
        Base.metadata.create_all(engine)

        def snapshot(url: str) -> dict[str, object]:
            local_engine = create_engine(url)
            inspector = inspect(local_engine)
            tables = sorted(t for t in inspector.get_table_names() if t != "alembic_version")
            result: dict[str, object] = {}
            for table in tables:
                result[table] = {
                    "columns": sorted(
                        (c["name"], str(c["type"]), bool(c["nullable"]))
                        for c in inspector.get_columns(table)
                    ),
                    "indexes": sorted(
                        (i["name"], tuple(i["column_names"]), bool(i["unique"]))
                        for i in inspector.get_indexes(table)
                    ),
                    "pk": tuple(inspector.get_pk_constraint(table)["constrained_columns"]),
                    "fks": sorted(
                        (
                            tuple(f["constrained_columns"]),
                            f["referred_table"],
                            tuple(f["referred_columns"]),
                        )
                        for f in inspector.get_foreign_keys(table)
                    ),
                }
            local_engine.dispose()
            return result

        assert snapshot(f"sqlite:///{migrated}") == snapshot(f"sqlite:///{expected}")

    def test_running_migrations_does_not_mute_application_logging(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Regression test for a classic Alembic trap.

        ``env.py`` calls ``logging.config.fileConfig``, whose
        ``disable_existing_loggers`` argument defaults to **True** -- so every
        logger not named in ``alembic.ini`` is switched off, including all of
        ``taskflow.*``. It is invisible when Alembic runs as its own process,
        and silently mutes the entire application whenever migrations run
        in-process: from this suite, or from a startup hook that upgrades the
        schema before serving traffic.
        """
        database = tmp_path / "logging.db"
        config = Config(str(BACKEND_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
        config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")

        app_logger = logging.getLogger("taskflow.events")
        command.upgrade(config, "head")

        assert app_logger.disabled is False

    def test_downgrade_is_reversible(self, tmp_path: pathlib.Path) -> None:
        """A migration you cannot undo is not a migration, it is a one-way door."""
        database = tmp_path / "roundtrip.db"
        config = Config(str(BACKEND_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
        config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")

        command.upgrade(config, "head")
        command.downgrade(config, "base")

        engine = create_engine(f"sqlite:///{database}")
        remaining = {t for t in inspect(engine).get_table_names() if t != "alembic_version"}
        engine.dispose()
        assert remaining == set()


class TestDatabaseConstraints:
    async def test_email_uniqueness_is_enforced_by_the_database(self, container) -> None:
        """The application also checks, but the index is what makes it true.

        Two concurrent signups both pass the read check; only a unique index
        can reject the loser.
        """
        async with container.session_factory() as session:
            session.add(user_to_model(make_user(email="clash@example.com")))
            await session.commit()

        async with container.session_factory() as session:
            session.add(user_to_model(make_user(email="clash@example.com")))
            with pytest.raises(IntegrityError):
                await session.commit()

    async def test_the_unit_of_work_translates_it_into_a_domain_error(self, container) -> None:
        # Otherwise a duplicate signup surfaces as a 500 with a psycopg
        # stack trace instead of a 409.
        uow = SqlAlchemyUnitOfWork(container.session_factory)
        async with uow as first:
            await first.users.add(make_user(email="translated@example.com"))
            await first.commit()

        uow = SqlAlchemyUnitOfWork(container.session_factory)
        with pytest.raises(AlreadyExistsError):
            async with uow as second:
                await second.users.add(make_user(email="translated@example.com"))
                await second.commit()

    async def test_completed_at_must_agree_with_the_status(self, container) -> None:
        """A DB-level invariant, because the ORM is not the only writer."""
        owner = make_user(email="constraint@example.com")
        async with container.session_factory() as session:
            session.add(user_to_model(owner))
            await session.commit()

        async with container.session_factory() as session:
            with pytest.raises(IntegrityError):
                await session.execute(
                    insert(TaskModel).values(
                        id=uuid4(),
                        title="Done but with no completion timestamp",
                        description="",
                        status=TaskStatus.DONE.value,
                        priority=TaskPriority.MEDIUM.value,
                        owner_id=owner.id,
                        assignee_id=None,
                        due_date=None,
                        completed_at=None,
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
                await session.commit()

    @pytest.mark.parametrize(
        ("column", "value"),
        [("status", "invented"), ("priority", "catastrophic")],
    )
    async def test_enum_columns_are_constrained(
        self, container, column: str, value: str
    ) -> None:
        owner = make_user(email=f"enum-{column}@example.com")
        async with container.session_factory() as session:
            session.add(user_to_model(owner))
            await session.commit()

        payload = {
            "id": uuid4(),
            "title": "Invalid enum value",
            "description": "",
            "status": TaskStatus.TODO.value,
            "priority": TaskPriority.MEDIUM.value,
            "owner_id": owner.id,
            "assignee_id": None,
            "due_date": None,
            "completed_at": None,
            "created_at": NOW,
            "updated_at": NOW,
        }
        payload[column] = value

        async with container.session_factory() as session:
            with pytest.raises(IntegrityError):
                await session.execute(insert(TaskModel).values(**payload))
                await session.commit()

    async def test_foreign_keys_are_enforced_on_sqlite(self, container) -> None:
        """SQLite ignores foreign keys unless the PRAGMA is set per connection.

        Without the engine event that enables it, ``ondelete`` rules are
        silently inert under SQLite -- so the tests would accept data that
        PostgreSQL rejects in production.
        """
        async with container.session_factory() as session:
            result = await session.execute(text("PRAGMA foreign_keys"))
            assert result.scalar() == 1

            with pytest.raises(IntegrityError):
                session.add(task_to_model(make_task(owner_id=uuid4())))
                await session.commit()

    async def test_deleting_a_user_cascades_to_owned_tasks(self, container) -> None:
        owner = make_user(email="cascade@example.com")
        task = make_task(owner_id=owner.id)

        async with container.session_factory() as session:
            session.add(user_to_model(owner))
            await session.flush()
            session.add(task_to_model(task))
            await session.commit()

        async with container.session_factory() as session:
            await session.execute(delete(UserModel).where(UserModel.id == owner.id))
            await session.commit()
            # ON DELETE CASCADE, enforced by the database rather than by a
            # tidy-up loop in application code.
            assert await session.get(TaskModel, task.id) is None


class TestTimezoneHandling:
    async def test_aware_datetimes_survive_the_round_trip(self, container) -> None:
        """The reason ``UTCDateTime`` exists.

        SQLite has no timezone type and hands back naive values, so a loaded
        ``due_date`` compared against ``datetime.now(UTC)`` would raise
        TypeError -- on SQLite only.
        """
        owner = make_user(email="tz@example.com")
        due = datetime(2027, 3, 14, 15, 9, 26, tzinfo=UTC)
        task = make_task(owner_id=owner.id, due_date=due)

        async with container.session_factory() as session:
            session.add(user_to_model(owner))
            await session.flush()
            session.add(task_to_model(task))
            await session.commit()

        async with container.session_factory() as session:
            row = await session.get(TaskModel, task.id)
            assert row is not None
            assert row.due_date is not None
            assert row.due_date.tzinfo is not None
            assert row.due_date == due
            # The comparison that would otherwise blow up.
            assert row.due_date > datetime.now(UTC) - timedelta(days=1)

    async def test_a_non_utc_offset_is_normalised(self, container) -> None:
        owner = make_user(email="offset@example.com")
        madrid = datetime(2027, 7, 1, 14, 0, tzinfo=UTC) + timedelta(hours=2)
        task = make_task(owner_id=owner.id, due_date=madrid)

        async with container.session_factory() as session:
            session.add(user_to_model(owner))
            await session.flush()
            session.add(task_to_model(task))
            await session.commit()

        async with container.session_factory() as session:
            row = await session.get(TaskModel, task.id)
            assert row is not None
            assert row.due_date == madrid
            assert row.due_date.utcoffset() == timedelta(0)

    async def test_naive_datetimes_are_refused_at_the_column(self, container) -> None:
        owner = make_user(email="naive@example.com")
        async with container.session_factory() as session:
            session.add(user_to_model(owner))
            await session.commit()

        async with container.session_factory() as session:
            # Loud failure beats a value that silently shifts by the local
            # offset of whichever machine wrote the row.
            with pytest.raises((StatementError, ValueError)):
                await session.execute(
                    insert(TaskModel).values(
                        id=uuid4(),
                        title="Naive timestamp",
                        description="",
                        status=TaskStatus.TODO.value,
                        priority=TaskPriority.MEDIUM.value,
                        owner_id=owner.id,
                        assignee_id=None,
                        due_date=datetime(2027, 1, 1, 12, 0),
                        completed_at=None,
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )


class TestMappers:
    async def test_user_round_trips_through_the_mapper(self, container) -> None:
        original = make_user(email="mapper@example.com", full_name="Mapper Person")

        async with container.session_factory() as session:
            session.add(user_to_model(original))
            await session.commit()

        async with container.session_factory() as session:
            row = await session.get(UserModel, original.id)
            assert row is not None
            restored = user_to_entity(row)

        assert restored.id == original.id
        assert restored.email == original.email
        assert restored.full_name == original.full_name
        assert restored.hashed_password == original.hashed_password
        assert restored.is_active == original.is_active

    async def test_task_round_trips_through_the_mapper(self, container) -> None:
        owner = make_user(email="taskmapper@example.com")
        original = make_task(
            owner_id=owner.id,
            title="Round trip me",
            description="With a description",
            priority=TaskPriority.URGENT,
            due_date=datetime(2027, 1, 1, tzinfo=UTC),
        )

        async with container.session_factory() as session:
            session.add(user_to_model(owner))
            await session.flush()
            session.add(task_to_model(original))
            await session.commit()

        async with container.session_factory() as session:
            row = await session.get(TaskModel, original.id)
            assert row is not None
            restored = task_to_entity(row)

        assert restored.id == original.id
        assert restored.title == original.title
        assert restored.description == original.description
        assert restored.status is original.status
        assert restored.priority is original.priority
        assert restored.due_date == original.due_date
        # A rehydrated aggregate must not arrive carrying events.
        assert restored.pull_events() == []


class TestRepositories:
    @pytest.fixture
    async def session(self, container):
        async with container.session_factory() as session:
            yield session

    async def test_get_many_batches_in_one_query(self, session: AsyncSession) -> None:
        """The N+1 guard.

        Resolving people row by row turns a 20-item page into 41 queries.
        """
        repo = SqlAlchemyUserRepository(session)
        people = [make_user(email=f"batch{i}@example.com") for i in range(5)]
        for person in people:
            await repo.add(person)
        await session.commit()

        found = await repo.get_many([p.id for p in people] + [uuid4()])

        assert len(found) == 5
        assert all(p.id in found for p in people)

    async def test_get_many_with_no_ids_does_not_query(self, session: AsyncSession) -> None:
        assert await SqlAlchemyUserRepository(session).get_many([]) == {}

    async def test_get_many_deduplicates_ids(self, session: AsyncSession) -> None:
        repo = SqlAlchemyUserRepository(session)
        person = make_user(email="dedupe@example.com")
        await repo.add(person)
        await session.commit()

        found = await repo.get_many([person.id, person.id, person.id])
        assert list(found) == [person.id]

    async def test_email_lookup_is_exact_on_the_normalised_value(
        self, session: AsyncSession
    ) -> None:
        repo = SqlAlchemyUserRepository(session)
        await repo.add(make_user(email="Lookup@Example.COM"))
        await session.commit()

        assert await repo.get_by_email(Email("lookup@example.com")) is not None
        assert await repo.get_by_email(Email("LOOKUP@EXAMPLE.COM")) is not None
        assert await repo.get_by_email(Email("other@example.com")) is None

    async def test_exists_with_email(self, session: AsyncSession) -> None:
        repo = SqlAlchemyUserRepository(session)
        await repo.add(make_user(email="exists@example.com"))
        await session.commit()

        assert await repo.exists_with_email(Email("exists@example.com")) is True
        assert await repo.exists_with_email(Email("missing@example.com")) is False

    async def test_user_directory_paginates_and_searches(self, session: AsyncSession) -> None:
        repo = SqlAlchemyUserRepository(session)
        for index in range(7):
            await repo.add(
                make_user(email=f"dir{index}@example.com", full_name=f"Person Number{index}")
            )
        await session.commit()

        page = await repo.find(UserFilter(), Pagination(page=1, page_size=3))
        assert len(page.items) == 3
        assert page.total == 7

        filtered = await repo.find(
            UserFilter(search="Number3"), Pagination(page=1, page_size=10)
        )
        assert [u.full_name.value for u in filtered.items] == ["Person Number3"]

    async def test_inactive_users_can_be_filtered_out(self, session: AsyncSession) -> None:
        repo = SqlAlchemyUserRepository(session)
        active = make_user(email="active@example.com")
        gone = make_user(email="gone@example.com")
        gone.deactivate(now=NOW)
        await repo.add(active)
        await repo.add(gone)
        await session.commit()

        page = await repo.find(UserFilter(is_active=True), Pagination())
        assert [u.email.value for u in page.items] == ["active@example.com"]

    async def test_task_update_writes_only_the_domain_columns(
        self, session: AsyncSession
    ) -> None:
        """``created_at`` is not the aggregate's to change."""
        user_repo = SqlAlchemyUserRepository(session)
        task_repo = SqlAlchemyTaskRepository(session)
        owner = make_user(email="update@example.com")
        await user_repo.add(owner)
        await session.flush()

        task = make_task(owner_id=owner.id, title="Before the update")
        await task_repo.add(task)
        await session.commit()
        original_created_at = task.created_at

        task.rename(TaskTitle("After the update"), now=NOW + timedelta(hours=2))
        await task_repo.update(task)
        await session.commit()

        reloaded = await task_repo.get(task.id)
        assert reloaded is not None
        assert reloaded.title.value == "After the update"
        assert reloaded.created_at == original_created_at
        assert reloaded.updated_at == NOW + timedelta(hours=2)

    async def test_delete_reports_whether_anything_was_removed(
        self, session: AsyncSession
    ) -> None:
        user_repo = SqlAlchemyUserRepository(session)
        task_repo = SqlAlchemyTaskRepository(session)
        owner = make_user(email="delete@example.com")
        await user_repo.add(owner)
        await session.flush()
        task = make_task(owner_id=owner.id)
        await task_repo.add(task)
        await session.commit()

        assert await task_repo.delete(task.id) is True
        await session.commit()
        assert await task_repo.delete(task.id) is False

    async def test_count_matches_find_total(self, session: AsyncSession) -> None:
        user_repo = SqlAlchemyUserRepository(session)
        task_repo = SqlAlchemyTaskRepository(session)
        owner = make_user(email="count@example.com")
        await user_repo.add(owner)
        await session.flush()
        for index in range(4):
            await task_repo.add(make_task(owner_id=owner.id, title=f"Counted {index}"))
        await session.commit()

        filters = TaskFilter(visible_to=owner.id)
        page = await task_repo.find(filters, Pagination(page=1, page_size=2))
        assert page.total == await task_repo.count(filters) == 4


class TestUnitOfWork:
    async def test_forgetting_to_commit_discards_the_write(self, container) -> None:
        """Fails closed.

        ``__aexit__`` rolls back unconditionally, so a use case that returns
        without committing loses the write rather than persisting half an
        operation.
        """
        user = make_user(email="uncommitted@example.com")

        uow = SqlAlchemyUnitOfWork(container.session_factory)
        async with uow as scope:
            await scope.users.add(user)
            # No commit.

        verify = SqlAlchemyUnitOfWork(container.session_factory)
        async with verify as scope:
            assert await scope.users.get(user.id) is None

    async def test_an_exception_rolls_everything_back(self, container) -> None:
        user = make_user(email="rollback@example.com")

        uow = SqlAlchemyUnitOfWork(container.session_factory)
        with pytest.raises(RuntimeError):
            async with uow as scope:
                await scope.users.add(user)
                raise RuntimeError("business rule failed halfway through")

        verify = SqlAlchemyUnitOfWork(container.session_factory)
        async with verify as scope:
            assert await scope.users.get(user.id) is None

    async def test_two_repositories_share_one_transaction(self, container) -> None:
        owner = make_user(email="atomic@example.com")
        task = make_task(owner_id=owner.id)

        uow = SqlAlchemyUnitOfWork(container.session_factory)
        async with uow as scope:
            await scope.users.add(owner)
            await scope.tasks.add(task)
            await scope.commit()

        verify = SqlAlchemyUnitOfWork(container.session_factory)
        async with verify as scope:
            assert await scope.users.get(owner.id) is not None
            assert await scope.tasks.get(task.id) is not None


class TestHealth:
    async def test_liveness_never_touches_the_database(self, client) -> None:
        response = await client.get("/health/live")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        # No database key: a liveness probe that checks the DB turns a brief
        # blip into a restart loop.
        assert body.get("database") is None

    async def test_readiness_reports_the_database(self, client) -> None:
        response = await client.get("/health/ready")
        assert response.status_code == 200
        assert response.json()["database"] == "ok"

    async def test_readiness_degrades_to_503_when_the_database_is_gone(
        self, client, container
    ) -> None:
        healthy = container.engine

        class _BrokenEngine:
            """Simulates an unreachable database without breaking teardown."""

            def connect(self) -> None:
                raise OSError("connection refused")

            async def dispose(self) -> None:
                return None

        container.engine = _BrokenEngine()
        try:
            response = await client.get("/health/ready")
        finally:
            # Restored so the fixture can still close the real pool.
            container.engine = healthy

        # 503 so the load balancer stops sending traffic, without the
        # orchestrator killing a container that is merely waiting.
        assert response.status_code == 503
        assert response.json()["database"] == "unavailable"
        assert response.json()["status"] == "degraded"

    async def test_root_redirects_to_the_docs(self, client) -> None:
        response = await client.get("/", follow_redirects=False)
        assert response.status_code in (302, 307)
        assert response.headers["location"] == "/docs"

    async def test_openapi_schema_is_served(self, client) -> None:
        response = await client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert "/api/v1/tasks" in schema["paths"]
        # The Authorize button needs the scheme to be declared.
        assert "JWT" in schema["components"]["securitySchemes"]
