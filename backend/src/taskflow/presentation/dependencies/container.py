"""Composition root.

The one module in the codebase that is allowed to know every concrete class.
Everything else receives its collaborators through a constructor, which is
what keeps the dependency graph acyclic and the layers independently
testable.

Note the direction of every import here: presentation -> infrastructure ->
application -> domain. Nothing points back outwards.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from taskflow.application.ports import Clock, EventPublisher, PasswordHasher, TokenService
from taskflow.application.ports.unit_of_work import UnitOfWork
from taskflow.infrastructure.config.settings import Settings
from taskflow.infrastructure.db.engine import create_engine, create_session_factory
from taskflow.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from taskflow.infrastructure.security import BcryptPasswordHasher, JwtTokenService
from taskflow.infrastructure.services import SystemClock
from taskflow.infrastructure.tasks import CeleryEventPublisher, InMemoryEventPublisher


class Container:
    """Owns the process-wide singletons and builds per-request objects.

    The split matters: the engine, hasher and token service are expensive to
    build and safe to share, so they are created once at startup. A
    ``UnitOfWork`` wraps one database transaction and must *not* be shared,
    so a new one is handed out per request.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

        self.engine: AsyncEngine = create_engine(settings)
        self.session_factory: async_sessionmaker[AsyncSession] = create_session_factory(
            self.engine
        )

        self.clock: Clock = SystemClock()
        self.password_hasher: PasswordHasher = BcryptPasswordHasher(
            rounds=settings.bcrypt_rounds
        )
        self.token_service: TokenService = JwtTokenService(
            secret_key=settings.secret_key.get_secret_value(),
            algorithm=settings.jwt_algorithm,
            issuer=settings.jwt_issuer,
            access_ttl=timedelta(minutes=settings.access_token_ttl_minutes),
            refresh_ttl=timedelta(days=settings.refresh_token_ttl_days),
            clock=self.clock,
        )
        self.event_publisher: EventPublisher = (
            CeleryEventPublisher(enabled=True)
            if settings.celery_enabled
            # With Celery off the app still works end-to-end; events are just
            # recorded in-process. That keeps ``docker compose`` optional for
            # someone who only wants to look at the API.
            else InMemoryEventPublisher()
        )

    def unit_of_work(self) -> UnitOfWork:
        """A fresh transaction scope. Never cache this."""
        return SqlAlchemyUnitOfWork(self.session_factory)

    async def dispose(self) -> None:
        """Close the connection pool on shutdown."""
        await self.engine.dispose()


def get_container(request: Request) -> Container:
    """Read the container off the app state populated by the lifespan hook."""
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]
