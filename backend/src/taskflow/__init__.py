"""TaskFlow -- a task management API on a Clean Architecture layout.

The package is organised in four layers, each depending only inwards:

``domain``
    Entities, value objects, domain events and repository ports. Plain
    Python with no third-party imports at all.
``application``
    Use cases that orchestrate the domain, plus the ports (clock, hasher,
    tokens, unit of work, event publisher) they need from outside.
``infrastructure``
    Adapters implementing those ports: SQLAlchemy, bcrypt, PyJWT, Celery.
``presentation``
    FastAPI routers, Pydantic schemas, dependency wiring and the mapping
    from domain errors onto HTTP status codes.

The direction of those dependencies is enforced by
``tests/unit/test_architecture.py`` rather than left to convention.
"""

__version__ = "1.0.0"
