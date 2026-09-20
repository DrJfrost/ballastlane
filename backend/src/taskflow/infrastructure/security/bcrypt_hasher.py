"""bcrypt password hasher."""

from __future__ import annotations

import bcrypt


class BcryptPasswordHasher:
    """Adapter over the ``bcrypt`` package.

    Used directly rather than through ``passlib``: passlib is unmaintained
    and its bcrypt backend breaks against bcrypt >= 4 (it reads the removed
    ``bcrypt.__about__.__version__`` and raises on import). The API we need is
    three functions wide, so the dependency bought nothing.
    """

    def __init__(self, rounds: int = 12) -> None:
        self._rounds = rounds

    def hash(self, plain_password: str) -> str:
        return bcrypt.hashpw(
            self._encode(plain_password), bcrypt.gensalt(self._rounds)
        ).decode()

    def verify(self, plain_password: str, hashed_password: str) -> bool:
        try:
            return bcrypt.checkpw(self._encode(plain_password), hashed_password.encode())
        except (ValueError, TypeError):
            # A malformed or empty stored hash must read as "wrong password",
            # not crash the login endpoint with a 500.
            return False

    def needs_rehash(self, hashed_password: str) -> bool:
        """True when the stored hash used fewer rounds than we now require."""
        try:
            cost = int(hashed_password.split("$")[2])
        except (IndexError, ValueError):
            return True
        return cost < self._rounds

    @staticmethod
    def _encode(plain_password: str) -> bytes:
        """Encode to UTF-8 and guard bcrypt's 72-byte input limit.

        bcrypt silently ignores anything past 72 bytes, so without this two
        different long passwords can authenticate the same account. Truncating
        explicitly keeps the behaviour visible in one place; the application
        layer separately caps password length at 128 characters.
        """
        return plain_password.encode("utf-8")[:72]
