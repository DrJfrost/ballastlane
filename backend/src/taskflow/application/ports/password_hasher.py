"""Password hashing port."""

from __future__ import annotations

from typing import Protocol


class PasswordHasher(Protocol):
    """Hashes and verifies passwords.

    Kept behind a port for two reasons: the domain must not depend on a
    crypto library, and the test suite can swap in a trivial fast hasher --
    bcrypt is deliberately slow, and paying ~250 ms per fixture user turns a
    fast suite into a slow one.
    """

    def hash(self, plain_password: str) -> str:
        """Return an opaque, self-describing hash of ``plain_password``."""
        ...

    def verify(self, plain_password: str, hashed_password: str) -> bool:
        """Constant-time-ish comparison; never raises on malformed hashes."""
        ...

    def needs_rehash(self, hashed_password: str) -> bool:
        """True when the hash uses outdated parameters and should be upgraded."""
        ...
