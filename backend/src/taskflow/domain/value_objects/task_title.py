"""Task title and description value objects."""

from __future__ import annotations

from dataclasses import dataclass

from taskflow.domain.errors import ValidationError

MAX_TITLE_LENGTH = 200
MIN_TITLE_LENGTH = 3
MAX_DESCRIPTION_LENGTH = 5_000


@dataclass(frozen=True, slots=True)
class TaskTitle:
    """A non-blank, length-bounded task title with normalised whitespace."""

    value: str

    def __post_init__(self) -> None:
        normalised = " ".join(self.value.split())
        if len(normalised) < MIN_TITLE_LENGTH:
            raise ValidationError(
                f"Title must be at least {MIN_TITLE_LENGTH} characters.",
                details={"field": "title", "min_length": MIN_TITLE_LENGTH},
            )
        if len(normalised) > MAX_TITLE_LENGTH:
            raise ValidationError(
                f"Title must be at most {MAX_TITLE_LENGTH} characters.",
                details={"field": "title", "max_length": MAX_TITLE_LENGTH},
            )
        object.__setattr__(self, "value", normalised)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class TaskDescription:
    """An optional, length-bounded free-text description."""

    value: str = ""

    def __post_init__(self) -> None:
        normalised = self.value.strip()
        if len(normalised) > MAX_DESCRIPTION_LENGTH:
            raise ValidationError(
                f"Description must be at most {MAX_DESCRIPTION_LENGTH} characters.",
                details={"field": "description", "max_length": MAX_DESCRIPTION_LENGTH},
            )
        object.__setattr__(self, "value", normalised)

    @property
    def is_empty(self) -> bool:
        return not self.value

    def __str__(self) -> str:
        return self.value
