"""Value object invariants."""

from __future__ import annotations

import pytest

from taskflow.domain.errors import ValidationError
from taskflow.domain.value_objects import Email, PersonName, TaskDescription, TaskTitle

pytestmark = pytest.mark.unit


class TestEmail:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("user@example.com", "user@example.com"),
            ("  User@Example.COM  ", "user@example.com"),
            ("first.last+tag@sub.domain.co.uk", "first.last+tag@sub.domain.co.uk"),
            ("UPPER@EXAMPLE.ORG", "upper@example.org"),
        ],
    )
    def test_normalises_case_and_whitespace(self, raw: str, expected: str) -> None:
        assert Email(raw).value == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            "no-at-sign",
            "@example.com",
            "user@",
            "user@example",
            "user@@example.com",
            "user name@example.com",
            "user@exam ple.com",
        ],
    )
    def test_rejects_invalid_addresses(self, raw: str) -> None:
        with pytest.raises(ValidationError):
            Email(raw)

    def test_rejects_addresses_over_the_rfc_limit(self) -> None:
        too_long = "a" * 250 + "@example.com"
        with pytest.raises(ValidationError, match="at most 254"):
            Email(too_long)

    def test_equality_is_by_normalised_value(self) -> None:
        # Two users cannot register "Ada@x.com" and "ada@x.com" separately,
        # so the value object must treat them as the same address.
        assert Email("Ada@Example.com") == Email("ada@example.com")
        assert len({Email("Ada@Example.com"), Email("ada@example.com")}) == 1

    def test_exposes_the_domain_part(self) -> None:
        assert Email("user@example.com").domain == "example.com"

    def test_is_immutable(self) -> None:
        email = Email("user@example.com")
        with pytest.raises(AttributeError):
            email.value = "other@example.com"  # type: ignore[misc]


class TestPersonName:
    def test_collapses_internal_whitespace(self) -> None:
        assert PersonName("  Ada   Byron   Lovelace ").value == "Ada Byron Lovelace"

    @pytest.mark.parametrize("raw", ["", " ", "A", "  x  "])
    def test_rejects_names_that_are_too_short(self, raw: str) -> None:
        with pytest.raises(ValidationError, match="at least 2"):
            PersonName(raw)

    def test_rejects_names_that_are_too_long(self) -> None:
        with pytest.raises(ValidationError, match="at most 120"):
            PersonName("x" * 121)

    @pytest.mark.parametrize(
        ("raw", "initials"),
        [("Ada Lovelace", "AL"), ("Grace", "G"), ("Jean Luc Picard", "JL")],
    )
    def test_initials_use_at_most_two_words(self, raw: str, initials: str) -> None:
        assert PersonName(raw).initials == initials


class TestTaskTitle:
    def test_collapses_whitespace(self) -> None:
        assert TaskTitle("  Write   the   docs ").value == "Write the docs"

    @pytest.mark.parametrize("raw", ["", "ab", "  a  "])
    def test_rejects_short_titles(self, raw: str) -> None:
        with pytest.raises(ValidationError, match="at least 3"):
            TaskTitle(raw)

    def test_rejects_long_titles(self) -> None:
        with pytest.raises(ValidationError, match="at most 200"):
            TaskTitle("x" * 201)

    def test_accepts_exactly_the_boundary_lengths(self) -> None:
        # Off-by-one at a boundary is the most common validation bug, so both
        # ends are asserted explicitly.
        assert len(TaskTitle("abc").value) == 3
        assert len(TaskTitle("x" * 200).value) == 200

    def test_error_carries_machine_readable_details(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            TaskTitle("ab")
        assert exc_info.value.details["field"] == "title"
        assert exc_info.value.details["min_length"] == 3
        assert exc_info.value.code == "validation_error"


class TestTaskDescription:
    def test_defaults_to_empty(self) -> None:
        description = TaskDescription()
        assert description.value == ""
        assert description.is_empty

    def test_strips_but_preserves_internal_newlines(self) -> None:
        description = TaskDescription("  line one\nline two  ")
        assert description.value == "line one\nline two"

    def test_rejects_descriptions_over_the_limit(self) -> None:
        with pytest.raises(ValidationError, match="at most 5000"):
            TaskDescription("x" * 5001)
