"""Async engine and session factory."""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from taskflow.infrastructure.config.settings import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    """Build the engine, with the pool configured per backend."""
    if settings.is_sqlite:
        # An in-memory SQLite database lives inside its connection, so the
        # default pool -- which hands out a *new* connection per checkout --
        # would give every request an empty database. StaticPool keeps one.
        kwargs: dict[str, object] = {
            "poolclass": StaticPool,
            "connect_args": {"check_same_thread": False},
        }
    else:
        kwargs = {
            "pool_size": settings.database_pool_size,
            "max_overflow": settings.database_max_overflow,
            # Recycles connections killed by an idle timeout on the database
            # side, which otherwise surface as a random 500 after a quiet period.
            "pool_pre_ping": settings.database_pool_pre_ping,
            "pool_recycle": 1800,
        }

    engine = create_async_engine(
        settings.database_url,
        echo=settings.database_echo,
        future=True,
        **kwargs,
    )

    if settings.is_sqlite:
        _enable_sqlite_foreign_keys(engine)

    return engine


def _enable_sqlite_foreign_keys(engine: AsyncEngine) -> None:
    """Turn on foreign-key enforcement for SQLite.

    SQLite ignores foreign keys unless asked, per connection. Without this,
    the ``ondelete`` rules declared on the models are silently inert under
    SQLite, so tests would happily accept data that PostgreSQL rejects in
    production -- the worst kind of difference between environments.
    """

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragma(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        # Attributes stay readable after ``commit()``; without this, touching
        # any loaded object post-commit triggers a lazy refresh, which in
        # async code raises MissingGreenlet instead of just being slow.
        expire_on_commit=False,
        autoflush=False,
    )
