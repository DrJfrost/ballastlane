"""User aggregate and pagination primitives."""

from __future__ import annotations

from datetime import timedelta

import pytest

from taskflow.domain.errors import ConflictError, ValidationError
from taskflow.domain.repositories import MAX_PAGE_SIZE, Page, Pagination
from taskflow.domain.value_objects import PersonName
from tests.conftest import NOW, make_user

pytestmark = pytest.mark.unit


class TestUser:
    def test_register_produces_an_active_user(self) -> None:
        user = make_user(email="New.User@Example.com", full_name="  New   User ")
        assert user.email.value == "new.user@example.com"
        assert user.full_name.value == "New User"
        assert user.is_active
        assert user.can_be_assigned_work

    def test_deactivate_then_reactivate(self) -> None:
        user = make_user()
        later = NOW + timedelta(days=1)

        user.deactivate(now=later)
        assert not user.is_active
        assert not user.can_be_assigned_work
        assert user.updated_at == later

        user.activate(now=later + timedelta(days=1))
        assert user.is_active

    def test_deactivating_twice_is_a_conflict(self) -> None:
        user = make_user()
        user.deactivate(now=NOW)
        with pytest.raises(ConflictError, match="already deactivated"):
            user.deactivate(now=NOW)

    def test_activating_an_active_user_is_a_conflict(self) -> None:
        with pytest.raises(ConflictError, match="already active"):
            make_user().activate(now=NOW)

    def test_rename_is_a_no_op_when_unchanged(self) -> None:
        user = make_user(full_name="Ada Lovelace")
        user.rename(PersonName("Ada Lovelace"), now=NOW + timedelta(days=1))
        assert user.updated_at == NOW

    def test_rename_updates_the_timestamp(self) -> None:
        user = make_user(full_name="Ada Lovelace")
        later = NOW + timedelta(days=1)
        user.rename(PersonName("Ada B Lovelace"), now=later)
        assert user.full_name.value == "Ada B Lovelace"
        assert user.updated_at == later

    def test_change_password_rejects_an_empty_hash(self) -> None:
        # Guards against an adapter silently returning "" and locking the
        # account into a state where any verify() fails.
        with pytest.raises(ConflictError):
            make_user().change_password("", now=NOW)

    def test_identity_equality(self) -> None:
        user = make_user()
        clone = make_user(email="different@example.com", user_id=user.id)
        assert user == clone
        assert len({user, clone}) == 1
        assert user != "not a user"

    def test_never_exposes_a_plaintext_password(self) -> None:
        # The aggregate has no field that could hold one.
        assert not hasattr(make_user(), "password")


class TestPagination:
    def test_offset_is_derived_from_a_one_based_page(self) -> None:
        assert Pagination(page=1, page_size=20).offset == 0
        assert Pagination(page=2, page_size=20).offset == 20
        assert Pagination(page=5, page_size=15).offset == 60

    @pytest.mark.parametrize(("page", "page_size"), [(0, 20), (-1, 20), (1, 0), (1, -5)])
    def test_rejects_nonsense_input(self, page: int, page_size: int) -> None:
        with pytest.raises(ValidationError):
            Pagination(page=page, page_size=page_size)

    def test_caps_the_page_size(self) -> None:
        # Without the cap, ?page_size=1000000 is a free denial-of-service.
        with pytest.raises(ValidationError, match="at most"):
            Pagination(page=1, page_size=MAX_PAGE_SIZE + 1)
        assert Pagination(page=1, page_size=MAX_PAGE_SIZE).page_size == MAX_PAGE_SIZE


class TestPage:
    def test_metadata_is_computed_not_stored(self) -> None:
        page = Page(items=[1, 2, 3], total=25, page=2, page_size=10)
        assert page.total_pages == 3
        assert page.has_next is True
        assert page.has_previous is True

    def test_first_and_last_page_flags(self) -> None:
        first = Page(items=[1], total=25, page=1, page_size=10)
        assert first.has_previous is False
        assert first.has_next is True

        last = Page(items=[1], total=25, page=3, page_size=10)
        assert last.has_next is False
        assert last.has_previous is True

    def test_empty_page(self) -> None:
        page: Page[int] = Page(items=(), total=0, page=1, page_size=10)
        assert page.total_pages == 0
        assert not page.has_next
        assert not page.has_previous

    def test_partial_last_page_rounds_up(self) -> None:
        assert Page(items=[1], total=21, page=3, page_size=10).total_pages == 3

    def test_map_preserves_metadata(self) -> None:
        page = Page(items=[1, 2, 3], total=25, page=2, page_size=10)
        mapped = page.map(str)
        assert list(mapped.items) == ["1", "2", "3"]
        assert (mapped.total, mapped.page, mapped.page_size) == (25, 2, 10)
        assert mapped.has_next is True

    def test_degenerate_page_size_does_not_divide_by_zero(self) -> None:
        assert Page(items=(), total=5, page=1, page_size=0).total_pages == 0
