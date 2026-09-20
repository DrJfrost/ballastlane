"""Domain layer: pure business rules.

Nothing in this package may import from ``application``, ``infrastructure``
or ``presentation``, nor from any third-party framework (no FastAPI, no
SQLAlchemy, no Pydantic). That constraint is enforced by a test in
``tests/unit/test_architecture.py``.
"""
