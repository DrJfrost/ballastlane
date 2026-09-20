"""Application *ports*: everything the use cases need from the outside world.

Each of these is implemented by an adapter under ``infrastructure/``. The use
cases only ever see the Protocol, which is what lets the whole application
layer be unit-tested with hand-written fakes and no I/O.
"""

from taskflow.application.ports.clock import Clock
from taskflow.application.ports.event_publisher import EventPublisher
from taskflow.application.ports.password_hasher import PasswordHasher
from taskflow.application.ports.token_service import (
    IssuedToken,
    TokenPayload,
    TokenService,
    TokenType,
)
from taskflow.application.ports.unit_of_work import UnitOfWork

__all__ = [
    "Clock",
    "EventPublisher",
    "IssuedToken",
    "PasswordHasher",
    "TokenPayload",
    "TokenService",
    "TokenType",
    "UnitOfWork",
]
