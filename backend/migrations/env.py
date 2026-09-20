"""Alembic environment.

Uses the *synchronous* driver on purpose: migrations are a one-shot
operational task, and running them through the async engine buys nothing
while adding an event loop to every ``alembic`` invocation (including the one
inside the Docker entrypoint).
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from taskflow.infrastructure.config.settings import get_settings
from taskflow.infrastructure.db.models import Base

config = context.config

if config.config_file_name is not None:
    # ``disable_existing_loggers`` defaults to True, which switches off every
    # logger that is not named in alembic.ini -- including all of
    # ``taskflow.*``. That is invisible when Alembic runs as its own process,
    # and silently mutes the whole application whenever migrations are run
    # in-process: from a test suite, or from a startup hook that calls
    # ``command.upgrade`` before serving traffic.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

settings = get_settings()

# The URL defaults to the application settings, so a plain
# ``alembic upgrade head`` can never be pointed at a different database than
# the app itself uses. An explicitly supplied URL still wins, which is what
# lets tests migrate a throwaway file and lets an operator target a specific
# database with ``alembic -x``.
if not config.get_main_option("sqlalchemy.url", None):
    config.set_main_option("sqlalchemy.url", settings.sync_database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of executing it (``alembic upgrade --sql``)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        user_module_prefix="taskflow_types.",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Detects type and default drift, which autogenerate misses by
            # default and which is exactly how schemas quietly diverge.
            compare_type=True,
            compare_server_default=True,
            # Custom column types (``UTCDateTime``) are rendered with this
            # prefix, which matches the import that ``script.py.mako`` puts at
            # the top of every revision. Without it autogenerate emits a
            # fully-qualified name with no import and the migration dies with
            # NameError on first run.
            user_module_prefix="taskflow_types.",
            # SQLite cannot ALTER most things; batch mode rewrites the table
            # instead, so one migration script runs on both backends.
            render_as_batch=settings.is_sqlite,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
