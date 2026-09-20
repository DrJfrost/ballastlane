"""Celery job bodies, settings guards and structured logging."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from taskflow.domain.enums import TaskStatus
from taskflow.infrastructure.config.settings import Environment, Settings
from taskflow.infrastructure.db.mappers import task_to_model, user_to_model
from taskflow.infrastructure.db.models import Base
from taskflow.infrastructure.observability.logging import (
    JsonFormatter,
    configure_logging,
    request_id_var,
)
from taskflow.infrastructure.tasks import jobs
from tests.conftest import make_task, make_user

pytestmark = pytest.mark.unit


@pytest.fixture
def sync_db(tmp_path, monkeypatch):
    """A throwaway synchronous database wired into the job module.

    The jobs use their own blocking engine (Celery workers are not an event
    loop), so they are tested against a real synchronous SQLite file rather
    than through the async stack.
    """
    url = f"sqlite:///{tmp_path / 'jobs.db'}"
    engine = create_engine(url, future=True)
    Base.metadata.create_all(engine)

    # Keep a handle on the real cached factory: after monkeypatch restores
    # the attribute the local name would point at the replacement lambda.
    real_engine_factory = jobs._engine
    real_engine_factory.cache_clear()
    monkeypatch.setattr(jobs, "_engine", lambda: engine)
    try:
        yield engine
    finally:
        engine.dispose()
        real_engine_factory.cache_clear()


@pytest.fixture
def delivered(monkeypatch) -> list[dict]:
    captured: list[dict] = []

    def fake_deliver(**kwargs):
        captured.append(kwargs)
        return {"status": "sent", "channel": kwargs["channel"], "recipient": kwargs["to"]}

    monkeypatch.setattr(jobs, "_deliver", fake_deliver)
    return captured


def seed(engine, *entities) -> None:
    with Session(engine) as session:
        for entity in entities:
            session.add(entity)
            session.flush()
        session.commit()


class TestAssignmentNotification:
    def test_notifies_the_assignee(self, sync_db, delivered) -> None:
        owner = make_user(email="owner@example.com", full_name="Owner Person")
        assignee = make_user(email="assignee@example.com", full_name="Assignee Person")
        seed(sync_db, user_to_model(owner), user_to_model(assignee))

        result = jobs.notify_task_assigned(
            task_id=str(uuid4()),
            task_title="Review the deploy plan",
            assignee_id=str(assignee.id),
            assigned_by=str(owner.id),
        )

        assert result["status"] == "sent"
        assert delivered[0]["to"] == "assignee@example.com"
        assert "Review the deploy plan" in delivered[0]["subject"]
        assert "Owner Person" in delivered[0]["body"]

    def test_a_deleted_assignee_is_skipped_rather_than_retried(
        self, sync_db, delivered
    ) -> None:
        """Retrying would never succeed, so it would just burn the queue."""
        result = jobs.notify_task_assigned(
            task_id=str(uuid4()),
            task_title="Orphaned task",
            assignee_id=str(uuid4()),
            assigned_by=str(uuid4()),
        )

        assert result == {"status": "skipped", "reason": "assignee_missing"}
        assert delivered == []


class TestCompletionNotification:
    def test_notifies_the_owner(self, sync_db, delivered) -> None:
        owner = make_user(email="owner@example.com", full_name="Owner Person")
        actor = make_user(email="doer@example.com", full_name="Doer Person")
        seed(sync_db, user_to_model(owner), user_to_model(actor))

        jobs.notify_task_completed(
            task_id=str(uuid4()),
            task_title="Ship the release",
            completed_by=str(actor.id),
            owner_id=str(owner.id),
            was_overdue=True,
        )

        assert delivered[0]["to"] == "owner@example.com"
        assert "after the due date" in delivered[0]["body"]

    def test_no_self_notification(self, sync_db, delivered) -> None:
        # Emailing someone about something they just did themselves is noise.
        owner = make_user(email="owner@example.com")
        seed(sync_db, user_to_model(owner))

        result = jobs.notify_task_completed(
            task_id=str(uuid4()),
            task_title="Self-completed",
            completed_by=str(owner.id),
            owner_id=str(owner.id),
            was_overdue=False,
        )

        assert result == {"status": "skipped", "reason": "actor_is_owner"}
        assert delivered == []


class TestDueDateNotification:
    def test_notifies_the_assignee(self, sync_db, delivered) -> None:
        owner = make_user(email="owner@example.com")
        assignee = make_user(email="assignee@example.com")
        task = make_task(owner_id=owner.id, assignee_id=assignee.id, title="Moved task")
        seed(
            sync_db,
            user_to_model(owner),
            user_to_model(assignee),
            task_to_model(task),
        )

        jobs.notify_due_date_changed(
            task_id=str(task.id),
            new_due_date="2027-01-01T00:00:00+00:00",
            changed_by=str(owner.id),
        )

        assert delivered[0]["to"] == "assignee@example.com"
        assert "2027-01-01" in delivered[0]["body"]

    def test_unassigned_task_notifies_nobody(self, sync_db, delivered) -> None:
        owner = make_user(email="owner@example.com")
        task = make_task(owner_id=owner.id)
        seed(sync_db, user_to_model(owner), task_to_model(task))

        result = jobs.notify_due_date_changed(
            task_id=str(task.id), new_due_date=None, changed_by=str(owner.id)
        )
        assert result == {"status": "skipped", "reason": "no_assignee"}


class TestOverdueScan:
    def test_sends_one_digest_per_person_not_one_per_task(self, sync_db, delivered) -> None:
        """A user with 40 overdue tasks gets one email, not 40."""
        owner = make_user(email="busy@example.com")
        past = datetime.now(UTC) - timedelta(days=3)
        models: list[object] = [user_to_model(owner)]
        for index in range(4):
            models.append(
                task_to_model(
                    make_task(owner_id=owner.id, title=f"Late task {index}", due_date=past)
                )
            )
        seed(sync_db, *models)

        result = jobs.scan_overdue_tasks()

        assert result == {"overdue_tasks": 4, "recipients": 1}
        assert len(delivered) == 1
        assert delivered[0]["to"] == "busy@example.com"
        assert delivered[0]["subject"] == "You have 4 overdue task(s)"
        for index in range(4):
            assert f"Late task {index}" in delivered[0]["body"]

    def test_ignores_closed_and_future_tasks(self, sync_db, delivered) -> None:
        owner = make_user(email="tidy@example.com")
        past = datetime.now(UTC) - timedelta(days=3)
        future = datetime.now(UTC) + timedelta(days=3)
        seed(
            sync_db,
            user_to_model(owner),
            task_to_model(
                make_task(
                    owner_id=owner.id,
                    title="Finished late",
                    due_date=past,
                    status=TaskStatus.DONE,
                    completed_at=past,
                )
            ),
            task_to_model(make_task(owner_id=owner.id, title="Due later", due_date=future)),
            task_to_model(make_task(owner_id=owner.id, title="No deadline")),
        )

        result = jobs.scan_overdue_tasks()

        assert result == {"overdue_tasks": 0, "recipients": 0}
        assert delivered == []

    def test_groups_by_owner(self, sync_db, delivered) -> None:
        past = datetime.now(UTC) - timedelta(days=1)
        first = make_user(email="first@example.com")
        second = make_user(email="second@example.com")
        seed(
            sync_db,
            user_to_model(first),
            user_to_model(second),
            task_to_model(make_task(owner_id=first.id, title="Task A late", due_date=past)),
            task_to_model(make_task(owner_id=second.id, title="Task B late", due_date=past)),
        )

        result = jobs.scan_overdue_tasks()

        assert result["recipients"] == 2
        assert {d["to"] for d in delivered} == {"first@example.com", "second@example.com"}

    def test_real_deliver_logs_instead_of_raising(self, caplog) -> None:
        # The default implementation is the seam a real provider replaces.
        with caplog.at_level(logging.INFO, logger="taskflow.jobs"):
            result = jobs._deliver(channel="test", to="a@b.co", subject="Subject", body="Body")
        assert result["status"] == "sent"
        assert "notification_sent" in caplog.text


class TestSettingsGuards:
    def test_local_defaults_are_permissive(self) -> None:
        settings = Settings(environment=Environment.LOCAL)
        assert settings.is_sqlite
        assert settings.effective_rate_limit_storage_url == "memory://"

    def test_production_refuses_a_short_secret(self) -> None:
        with pytest.raises(ValueError, match="SECRET_KEY"):
            Settings(
                environment=Environment.PRODUCTION,
                secret_key="too-short",
                database_url="postgresql+asyncpg://u:p@h/db",
                rate_limit_storage_url="redis://r:6379/2",
            )

    def test_production_refuses_debug_mode(self) -> None:
        with pytest.raises(ValueError, match="DEBUG"):
            Settings(
                environment=Environment.PRODUCTION,
                secret_key="x" * 40,
                debug=True,
                database_url="postgresql+asyncpg://u:p@h/db",
                rate_limit_storage_url="redis://r:6379/2",
            )

    def test_production_refuses_sqlite(self) -> None:
        with pytest.raises(ValueError, match="SQLite"):
            Settings(
                environment=Environment.PRODUCTION,
                secret_key="x" * 40,
                database_url="sqlite+aiosqlite:///./prod.db",
                rate_limit_storage_url="redis://r:6379/2",
            )

    def test_production_refuses_in_memory_rate_limiting(self, monkeypatch) -> None:
        """Per-process counters multiply the limit by the worker count."""
        # The test environment exports a value; remove it so the field falls
        # back to its unset default, which is what the guard is about.
        monkeypatch.delenv("RATE_LIMIT_STORAGE_URL", raising=False)

        with pytest.raises(ValueError, match="RATE_LIMIT_STORAGE_URL"):
            Settings(
                environment=Environment.PRODUCTION,
                secret_key="x" * 40,
                database_url="postgresql+asyncpg://u:p@h/db",
                # The suite disables limiting globally; the guard only applies
                # when it is on, so it has to be enabled here.
                rate_limit_enabled=True,
            )

    def test_disabled_rate_limiting_needs_no_storage(self, monkeypatch) -> None:
        monkeypatch.delenv("RATE_LIMIT_STORAGE_URL", raising=False)
        settings = Settings(
            environment=Environment.PRODUCTION,
            secret_key="x" * 40,
            database_url="postgresql+asyncpg://u:p@h/db",
            rate_limit_enabled=False,
        )
        assert settings.effective_rate_limit_storage_url == "memory://"

    def test_a_valid_production_config_is_accepted(self) -> None:
        settings = Settings(
            environment=Environment.PRODUCTION,
            secret_key="x" * 40,
            database_url="postgresql+asyncpg://u:p@h/db",
            rate_limit_storage_url="redis://r:6379/2",
        )
        assert settings.environment.is_production_like
        assert not settings.is_sqlite
        assert settings.sync_database_url == "postgresql+psycopg://u:p@h/db"

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("http://a.com,http://b.com", ("http://a.com", "http://b.com")),
            ("http://a.com , http://b.com ", ("http://a.com", "http://b.com")),
            ("http://a.com", ("http://a.com",)),
            ("", ()),
        ],
    )
    def test_cors_origins_accept_a_comma_separated_string(
        self, raw: str, expected: tuple[str, ...]
    ) -> None:
        # Keeps docker-compose readable; a JSON array in YAML is unpleasant.
        assert Settings(cors_origins=raw).cors_origins == expected


class TestStructuredLogging:
    def test_emits_one_json_object_per_record(self) -> None:
        record = logging.LogRecord(
            name="taskflow.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="something_happened",
            args=(),
            exc_info=None,
        )
        payload = json.loads(JsonFormatter().format(record))

        assert payload["level"] == "INFO"
        assert payload["logger"] == "taskflow.test"
        assert payload["message"] == "something_happened"
        assert "timestamp" in payload

    def test_extra_fields_become_top_level_keys(self) -> None:
        record = logging.LogRecord(
            name="taskflow.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="task_created",
            args=(),
            exc_info=None,
        )
        record.task_id = "abc-123"
        record.duration_ms = 12.5

        payload = json.loads(JsonFormatter().format(record))

        # Queryable in a log aggregator, unlike an interpolated string.
        assert payload["task_id"] == "abc-123"
        assert payload["duration_ms"] == 12.5

    def test_the_request_id_is_attached_automatically(self) -> None:
        """A use case that knows nothing about HTTP still logs correlated."""
        token = request_id_var.set("trace-abc")
        try:
            record = logging.LogRecord(
                name="taskflow.domain",
                level=logging.INFO,
                pathname=__file__,
                lineno=1,
                msg="rule_applied",
                args=(),
                exc_info=None,
            )
            payload = json.loads(JsonFormatter().format(record))
        finally:
            request_id_var.reset(token)

        assert payload["request_id"] == "trace-abc"

    def test_exceptions_are_serialised(self) -> None:
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record = logging.LogRecord(
                name="taskflow.test",
                level=logging.ERROR,
                pathname=__file__,
                lineno=1,
                msg="failed",
                args=(),
                exc_info=sys.exc_info(),
            )
        payload = json.loads(JsonFormatter().format(record))
        assert "ValueError: boom" in payload["exception"]

    def test_repeated_configuration_does_not_stack_handlers(self) -> None:
        """Idempotent: configuring twice must not double every log line."""
        own = "_taskflow_owned_handler"

        configure_logging(level="INFO", as_json=True)
        after_first = sum(getattr(h, own, False) for h in logging.getLogger().handlers)
        configure_logging(level="INFO", as_json=True)
        after_second = sum(getattr(h, own, False) for h in logging.getLogger().handlers)

        assert after_first == after_second == 1

    def test_foreign_handlers_are_left_alone(self) -> None:
        """Wiping ``root.handlers`` breaks the host process silently.

        pytest's own log capture lives on the root logger, and so do APM
        agents and gunicorn handlers. Removing them makes logs appear to
        vanish for reasons that are very hard to trace back here.
        """
        root = logging.getLogger()
        foreign = logging.NullHandler()
        root.addHandler(foreign)
        try:
            configure_logging(level="INFO", as_json=True)
            assert foreign in root.handlers
        finally:
            root.removeHandler(foreign)

    def test_plain_text_mode_is_available_for_local_development(self) -> None:
        configure_logging(level="DEBUG", as_json=False)
        handler = logging.getLogger().handlers[0]
        assert not isinstance(handler.formatter, JsonFormatter)
        # Leave the suite in a predictable state.
        configure_logging(level="WARNING", as_json=False)
