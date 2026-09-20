"""Human name value object."""

from __future__ import annotations

from dataclasses import dataclass

from taskflow.domain.errors import ValidationError

MIN_NAME_LENGTH = 2
MAX_NAME_LENGTH = 120


@dataclass(frozen=True, slots=True)
class PersonName:
    """A displayable full name with collapsed internal whitespace."""

    value: str

    def __post_init__(self) -> None:
        normalised = " ".join(self.value.split())
        if len(normalised) < MIN_NAME_LENGTH:
            raise ValidationError(
                f"Full name must be at least {MIN_NAME_LENGTH} characters.",
                details={"field": "full_name", "min_length": MIN_NAME_LENGTH},
            )
        if len(normalised) > MAX_NAME_LENGTH:
            raise ValidationError(
                f"Full name must be at most {MAX_NAME_LENGTH} characters.",
                details={"field": "full_name", "max_length": MAX_NAME_LENGTH},
            )
        object.__setattr__(self, "value", normalised)

    @property
    def initials(self) -> str:
        return "".join(part[0].upper() for part in self.value.split()[:2])

    def __str__(self) -> str:
        return self.value
