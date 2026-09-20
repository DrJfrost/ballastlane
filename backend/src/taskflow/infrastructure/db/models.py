"""SQLAlchemy ORM models.

Deliberately *separate* from the domain entities. Keeping one class for both
is tempting and shorter, but it means the aggregate inherits from
``DeclarativeBase``, so every unit test needs metadata, lazy loading can fire
I/O from inside a business rule, and a column rename becomes a domain change.
The cost of that separation is the explicit mapper in ``mappers.py``, which is
about 60 lines and fully covered by tests.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    MetaData,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from taskflow.domain.enums import TaskPriority, TaskStatus
from taskflow.infrastructure.db.types import UTCDateTime

#: Explicit constraint names matter for migrations: without a convention the
#: database assigns its own (``users_email_key`` on Postgres, something else
#: on SQLite), and a later ``op.drop_constraint`` has no portable name to
#: reference.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base with a stable naming convention for constraints."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    # ``text("true")`` rather than ``text("1")``: Postgres rejects an integer
    # literal as a boolean default, while SQLite accepts both.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    __table_args__ = (
        # The application also checks for duplicates to return a friendly
        # 409, but *this* is what makes it true: two concurrent signups both
        # pass the read check and only the index can reject the loser.
        Index("uq_users_email", "email", unique=True),
    )


class TaskModel(Base):
    __tablename__ = "tasks"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    status: Mapped[TaskStatus] = mapped_column(String(20), nullable=False)
    priority: Mapped[TaskPriority] = mapped_column(String(10), nullable=False)

    owner_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        # Deleting a user removes their tasks. ``ondelete`` is declared so the
        # database enforces it even when rows are removed outside the ORM.
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    assignee_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        # An assignee leaving must not delete other people's tasks; the task
        # simply becomes unassigned.
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    due_date: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    # These relationships are declared for *flush ordering*, not for loading.
    #
    # A foreign-key column alone does not tell the ORM's unit of work that
    # users must be inserted before tasks -- that dependency comes from the
    # mapper graph. Without them, adding a user and a task in one transaction
    # emits the INSERTs in an arbitrary order and trips the foreign key.
    #
    # ``lazy="raise"`` keeps the aggregate boundary intact: reading
    # ``row.owner`` raises instead of quietly emitting a SELECT, so people are
    # still resolved by the explicit batch load in ``hydration.py`` and a
    # lazy-load can never fire from inside a business rule.
    # Not ``viewonly``: a view-only relationship is deliberately excluded
    # from the unit-of-work dependency sort, which would defeat the entire
    # purpose of declaring these.
    owner: Mapped[UserModel] = relationship(foreign_keys=[owner_id], lazy="raise")
    assignee: Mapped[UserModel | None] = relationship(foreign_keys=[assignee_id], lazy="raise")

    __table_args__ = (
        CheckConstraint(
            "status IN ('todo', 'in_progress', 'done', 'cancelled')",
            name="task_status_valid",
        ),
        CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'urgent')",
            name="task_priority_valid",
        ),
        # A completed task must record *when*, and an open one must not.
        # Enforced in the database because reports depend on it and the ORM
        # is not the only writer (migrations, fixtures, manual fixes).
        CheckConstraint(
            "(status = 'done' AND completed_at IS NOT NULL)"
            " OR (status <> 'done' AND completed_at IS NULL)",
            name="task_completed_at_consistent",
        ),
        # The list endpoint always filters by owner or assignee and usually
        # sorts by due date, so these are the two composite indexes that
        # actually get used. Indexing every column instead would slow writes
        # down for nothing.
        Index("ix_tasks_owner_id_status", "owner_id", "status"),
        Index("ix_tasks_assignee_id_status", "assignee_id", "status"),
        Index("ix_tasks_due_date", "due_date"),
        Index("ix_tasks_created_at", "created_at"),
    )
