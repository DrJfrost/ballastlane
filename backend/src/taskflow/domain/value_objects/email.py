"""Email value object."""

from __future__ import annotations

import re
from dataclasses import dataclass

from taskflow.domain.errors import ValidationError

# Intentionally pragmatic rather than RFC 5322-complete: a stricter regex
# rejects valid addresses, and the only real test of an address is sending
# mail to it. What matters here is the shape, the length limit and the
# normalisation that the uniqueness rule depends on.
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

MAX_EMAIL_LENGTH = 254  # RFC 5321 limit on the whole address


@dataclass(frozen=True, slots=True)
class Email:
    """A syntactically valid, normalised (lower-cased, trimmed) email address."""

    value: str

    def __post_init__(self) -> None:
        normalised = self.value.strip().lower()
        if not normalised:
            raise ValidationError("Email must not be empty.", details={"field": "email"})
        if len(normalised) > MAX_EMAIL_LENGTH:
            raise ValidationError(
                f"Email must be at most {MAX_EMAIL_LENGTH} characters.",
                details={"field": "email", "max_length": MAX_EMAIL_LENGTH},
            )
        if not _EMAIL_RE.match(normalised):
            raise ValidationError(
                "Email is not a valid address.", details={"field": "email", "value": self.value}
            )
        # Frozen dataclasses forbid plain assignment; this is the sanctioned
        # way to normalise in __post_init__.
        object.__setattr__(self, "value", normalised)

    @property
    def domain(self) -> str:
        return self.value.rsplit("@", 1)[1]

    def __str__(self) -> str:
        return self.value
