"""Filtering, sorting and pagination over HTTP.

These run against real SQL, which is the point: the in-memory fake in
``tests/fakes.py`` could agree with the use case and still disagree with the
database. Anything asserted here is asserted about the generated query.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from taskflow.infrastructure.db.models import TaskModel
from tests.conftest import auth, user_id_of

pytestmark = [pytest.mark.integration]


def iso(offset: timedelta) -> str:
    return (datetime.now(UTC) + offset).isoformat().replace("+00:00", "Z")


async def force_due_date(container, task_id: str, moment: datetime) -> None:
    """Backdate a deadline directly in the database.

    The API refuses to *set* a past deadline (a deliberate domain rule), but
    a task whose deadline has since passed is an entirely normal state that
    the overdue filter has to handle. Writing the row is the honest way to
    reach it.
    """
    async with container.session_factory() as session:
        await session.execute(
            # The id column is a real UUID type, so the string from the JSON
            # response has to be parsed rather than bound as text.
            update(TaskModel).where(TaskModel.id == UUID(task_id)).values(due_date=moment)
        )
        await session.commit()


@pytest.fixture
async def dataset(client: AsyncClient, container, alice, bob) -> dict[str, str]:
    """A small corpus that exercises every filter."""
    ids: dict[str, str] = {}

    async def add(key: str, **payload) -> None:
        response = await client.post(
            "/api/v1/tasks",
            headers=auth(alice),
            json={"title": f"Task {key}"} | payload,
        )
        assert response.status_code == 201, response.text
        ids[key] = response.json()["id"]

    await add("urgent_soon", priority="urgent", due_date=iso(timedelta(days=1)))
    await add("high_later", priority="high", due_date=iso(timedelta(days=20)))
    await add("low_undated", priority="low")
    await add("medium_assigned", priority="medium", assignee_id=user_id_of(bob))
    await add("searchable", description="mentions kubernetes explicitly")
    await add("to_be_done", priority="high", due_date=iso(timedelta(days=5)))
    await add("to_be_overdue", priority="urgent", due_date=iso(timedelta(days=2)))

    # Move one to done, and backdate another so it becomes overdue.
    await client.post(f"/api/v1/tasks/{ids['to_be_done']}/complete", headers=auth(alice))
    await force_due_date(container, ids["to_be_overdue"], datetime.now(UTC) - timedelta(days=3))

    # A task owned by bob and assigned to alice, to test the two scopes.
    response = await client.post(
        "/api/v1/tasks",
        headers=auth(bob),
        json={"title": "Task owned by bob", "assignee_id": user_id_of(alice)},
    )
    ids["owned_by_bob"] = response.json()["id"]
    return ids


async def titles(client: AsyncClient, headers: dict[str, str], query: str) -> list[str]:
    response = await client.get(f"/api/v1/tasks?{query}", headers=auth(headers))
    assert response.status_code == 200, response.text
    return [item["title"] for item in response.json()["items"]]


class TestVisibility:
    async def test_lists_owned_and_assigned_only(
        self, client: AsyncClient, dataset, alice, carol
    ) -> None:
        mine = await titles(client, alice, "page_size=100")
        assert "Task owned by bob" in mine  # assigned to alice
        assert len(mine) == 8

        # Carol is a party to none of them.
        assert await titles(client, carol, "page_size=100") == []

    async def test_created_by_me_excludes_assigned_work(
        self, client: AsyncClient, dataset, alice
    ) -> None:
        result = await titles(client, alice, "created_by_me=true&page_size=100")
        assert "Task owned by bob" not in result
        assert len(result) == 7

    async def test_assigned_to_me_shows_only_delegated_work(
        self, client: AsyncClient, dataset, alice
    ) -> None:
        assert await titles(client, alice, "assigned_to_me=true") == ["Task owned by bob"]

    async def test_unassigned_only(self, client: AsyncClient, dataset, alice) -> None:
        result = await titles(client, alice, "unassigned_only=true&page_size=100")
        assert "Task medium_assigned" not in result
        assert "Task low_undated" in result


class TestStatusAndPriority:
    async def test_single_status(self, client: AsyncClient, dataset, alice) -> None:
        assert await titles(client, alice, "status=done") == ["Task to_be_done"]

    async def test_multiple_statuses_are_combined(
        self, client: AsyncClient, dataset, alice
    ) -> None:
        result = await titles(client, alice, "status=todo&status=done&page_size=100")
        assert "Task to_be_done" in result
        assert len(result) == 8

    async def test_multiple_priorities(self, client: AsyncClient, dataset, alice) -> None:
        result = await titles(client, alice, "priority=urgent&priority=high&page_size=100")
        assert set(result) == {
            "Task urgent_soon",
            "Task high_later",
            "Task to_be_done",
            "Task to_be_overdue",
        }

    async def test_unknown_status_value_is_422(
        self, client: AsyncClient, dataset, alice
    ) -> None:
        response = await client.get("/api/v1/tasks?status=invented", headers=auth(alice))
        assert response.status_code == 422


class TestDueDate:
    async def test_due_before(self, client: AsyncClient, dataset, alice) -> None:
        result = await titles(
            client, alice, f"due_before={iso(timedelta(days=3))}&page_size=100"
        )
        assert "Task urgent_soon" in result
        assert "Task high_later" not in result
        # Undated tasks have no deadline to compare, so they are excluded.
        assert "Task low_undated" not in result

    async def test_due_after(self, client: AsyncClient, dataset, alice) -> None:
        result = await titles(
            client, alice, f"due_after={iso(timedelta(days=10))}&page_size=100"
        )
        assert result == ["Task high_later"]

    async def test_due_window(self, client: AsyncClient, dataset, alice) -> None:
        result = await titles(
            client,
            alice,
            f"due_after={iso(timedelta(hours=1))}&due_before={iso(timedelta(days=7))}"
            "&page_size=100",
        )
        assert set(result) == {"Task urgent_soon", "Task to_be_done"}

    async def test_inverted_window_is_rejected(
        self, client: AsyncClient, dataset, alice
    ) -> None:
        response = await client.get(
            f"/api/v1/tasks?due_after={iso(timedelta(days=10))}"
            f"&due_before={iso(timedelta(days=1))}",
            headers=auth(alice),
        )
        # A clear 422 beats a silently empty list.
        assert response.status_code == 422
        assert "due_before" in response.text

    async def test_has_due_date_true_and_false(
        self, client: AsyncClient, dataset, alice
    ) -> None:
        dated = await titles(client, alice, "has_due_date=true&page_size=100")
        undated = await titles(client, alice, "has_due_date=false&page_size=100")

        assert "Task low_undated" in undated
        assert "Task low_undated" not in dated
        assert set(dated).isdisjoint(undated)

    async def test_overdue_only_requires_an_open_status(
        self, client: AsyncClient, dataset, alice, container
    ) -> None:
        assert await titles(client, alice, "overdue_only=true") == ["Task to_be_overdue"]

        # Completing it removes it from the overdue list: finished-but-late
        # work is history, not a to-do.
        await client.post(
            f"/api/v1/tasks/{dataset['to_be_overdue']}/complete", headers=auth(alice)
        )
        assert await titles(client, alice, "overdue_only=true") == []

    async def test_overdue_tasks_are_flagged_in_the_payload(
        self, client: AsyncClient, dataset, alice
    ) -> None:
        response = await client.get("/api/v1/tasks?overdue_only=true", headers=auth(alice))
        item = response.json()["items"][0]
        assert item["is_overdue"] is True
        assert item["days_until_due"] is not None
        assert item["days_until_due"] < 0


class TestSearch:
    async def test_matches_the_description(self, client: AsyncClient, dataset, alice) -> None:
        assert await titles(client, alice, "search=kubernetes") == ["Task searchable"]

    async def test_is_case_insensitive(self, client: AsyncClient, dataset, alice) -> None:
        assert await titles(client, alice, "search=KUBERNETES") == ["Task searchable"]

    async def test_matches_the_title(self, client: AsyncClient, dataset, alice) -> None:
        assert await titles(client, alice, "search=urgent_soon") == ["Task urgent_soon"]

    async def test_percent_is_matched_literally_not_as_a_wildcard(
        self, client: AsyncClient, dataset, alice
    ) -> None:
        """Unescaped, ``%`` in LIKE means "anything"."""
        # No seeded title contains a literal percent sign, so a correct
        # implementation finds nothing. Without escaping this returns
        # everything, which is how "search for 100%" quietly breaks.
        assert await titles(client, alice, "search=%") == []

    async def test_underscore_is_matched_literally_not_as_any_character(
        self, client: AsyncClient, dataset, alice
    ) -> None:
        """Unescaped, ``_`` in LIKE means "exactly one of any character"."""
        result = await titles(client, alice, "search=_&page_size=100")
        everything = await titles(client, alice, "page_size=100")

        # The seeded titles use snake_case keys, so several do contain a
        # literal underscore -- but not all of them. Treating ``_`` as a
        # wildcard would return the full set.
        assert result, "expected the literal-underscore titles to match"
        assert len(result) < len(everything)
        assert all("_" in title for title in result)
        assert "Task searchable" not in result

    async def test_injection_attempt_is_treated_as_text(
        self, client: AsyncClient, dataset, alice
    ) -> None:
        # Parameter binding, so this is just a string that matches nothing.
        result = await titles(client, alice, "search=' OR 1=1 --")
        assert result == []
        # And the table is still there.
        assert len(await titles(client, alice, "page_size=100")) == 8

    async def test_blank_search_is_ignored(self, client: AsyncClient, dataset, alice) -> None:
        assert len(await titles(client, alice, "search=%20%20&page_size=100")) == 8


class TestSorting:
    async def test_priority_uses_business_order_not_the_alphabet(
        self, client: AsyncClient, dataset, alice
    ) -> None:
        response = await client.get(
            "/api/v1/tasks?sort_by=priority&sort_dir=desc&page_size=100",
            headers=auth(alice),
        )
        weights = {"low": 0, "medium": 1, "high": 2, "urgent": 3}
        order = [weights[item["priority"]] for item in response.json()["items"]]

        # Sorted by the string column this would begin with "urgent" only by
        # accident; by weight it is monotonic.
        assert order == sorted(order, reverse=True)
        assert response.json()["items"][0]["priority"] == "urgent"

    async def test_priority_ascending(self, client: AsyncClient, dataset, alice) -> None:
        response = await client.get(
            "/api/v1/tasks?sort_by=priority&sort_dir=asc&page_size=100",
            headers=auth(alice),
        )
        assert response.json()["items"][0]["priority"] == "low"

    async def test_undated_tasks_sort_last_in_both_directions(
        self, client: AsyncClient, dataset, alice
    ) -> None:
        for direction in ("asc", "desc"):
            response = await client.get(
                f"/api/v1/tasks?sort_by=due_date&sort_dir={direction}&page_size=100",
                headers=auth(alice),
            )
            due_dates = [item["due_date"] for item in response.json()["items"]]
            first_null = next(
                (i for i, value in enumerate(due_dates) if value is None),
                len(due_dates),
            )
            # Nothing dated appears after the first undated task.
            assert all(value is None for value in due_dates[first_null:])

    async def test_title_sorting(self, client: AsyncClient, dataset, alice) -> None:
        result = await titles(client, alice, "sort_by=title&sort_dir=asc&page_size=100")
        assert result == sorted(result)

    async def test_unknown_sort_key_is_422(self, client: AsyncClient, dataset, alice) -> None:
        # Whitelisted, so an arbitrary value cannot reach the ORDER BY clause.
        response = await client.get(
            "/api/v1/tasks?sort_by=hashed_password", headers=auth(alice)
        )
        assert response.status_code == 422


class TestPagination:
    async def test_metadata_is_consistent(self, client: AsyncClient, dataset, alice) -> None:
        response = await client.get("/api/v1/tasks?page=1&page_size=3", headers=auth(alice))
        meta = response.json()["meta"]

        assert meta == {
            "page": 1,
            "page_size": 3,
            "total": 8,
            "total_pages": 3,
            "has_next": True,
            "has_previous": False,
        }
        assert len(response.json()["items"]) == 3

    async def test_pages_do_not_overlap_or_skip(
        self, client: AsyncClient, dataset, alice
    ) -> None:
        """The reason ORDER BY carries a tiebreaker on ``id``.

        Without a total order, rows that tie on the sort key can shuffle
        between queries, so an item shows up on two pages or on none.
        """
        seen: list[str] = []
        for page in (1, 2, 3):
            response = await client.get(
                f"/api/v1/tasks?page={page}&page_size=3&sort_by=priority",
                headers=auth(alice),
            )
            seen.extend(item["id"] for item in response.json()["items"])

        assert len(seen) == 8
        assert len(set(seen)) == 8

    async def test_last_page_flags(self, client: AsyncClient, dataset, alice) -> None:
        response = await client.get("/api/v1/tasks?page=3&page_size=3", headers=auth(alice))
        meta = response.json()["meta"]
        assert meta["has_next"] is False
        assert meta["has_previous"] is True
        assert len(response.json()["items"]) == 2

    async def test_page_past_the_end_is_empty_but_keeps_the_total(
        self, client: AsyncClient, dataset, alice
    ) -> None:
        response = await client.get("/api/v1/tasks?page=99&page_size=10", headers=auth(alice))
        assert response.json()["items"] == []
        assert response.json()["meta"]["total"] == 8

    @pytest.mark.parametrize("query", ["page=0", "page=-1", "page_size=0", "page_size=101"])
    async def test_rejects_out_of_range_paging(
        self, client: AsyncClient, dataset, alice, query: str
    ) -> None:
        response = await client.get(f"/api/v1/tasks?{query}", headers=auth(alice))
        assert response.status_code == 422

    async def test_page_size_is_capped(self, client: AsyncClient, dataset, alice) -> None:
        # The cap is what stops ?page_size=1000000 from being a free DoS.
        response = await client.get("/api/v1/tasks?page_size=100", headers=auth(alice))
        assert response.status_code == 200
        assert response.json()["meta"]["page_size"] == 100


class TestCombinedFilters:
    async def test_filters_compose(self, client: AsyncClient, dataset, alice) -> None:
        result = await titles(
            client,
            alice,
            "status=todo&priority=urgent&has_due_date=true"
            "&sort_by=due_date&sort_dir=asc&page_size=100",
        )
        assert set(result) == {"Task urgent_soon", "Task to_be_overdue"}

    async def test_a_filter_matching_nothing_returns_a_well_formed_empty_page(
        self, client: AsyncClient, dataset, alice
    ) -> None:
        response = await client.get("/api/v1/tasks?status=cancelled", headers=auth(alice))
        assert response.status_code == 200
        assert response.json() == {
            "items": [],
            "meta": {
                "page": 1,
                "page_size": 20,
                "total": 0,
                "total_pages": 0,
                "has_next": False,
                "has_previous": False,
            },
        }


class TestStats:
    async def test_counters_match_the_list_endpoint(
        self, client: AsyncClient, dataset, alice
    ) -> None:
        response = await client.get("/api/v1/tasks/stats", headers=auth(alice))
        assert response.status_code == 200
        stats = response.json()

        assert stats["total"] == 8
        assert stats["done"] == 1
        assert stats["overdue"] == 1
        assert stats["assigned_to_me"] == 1
        assert (
            stats["todo"] + stats["in_progress"] + stats["done"] + stats["cancelled"]
            == stats["total"]
        )

    async def test_stats_route_is_not_shadowed_by_the_id_route(
        self, client: AsyncClient, alice
    ) -> None:
        # ``/tasks/stats`` must not be parsed as ``/tasks/{task_id}``.
        response = await client.get("/api/v1/tasks/stats", headers=auth(alice))
        assert response.status_code == 200
        assert "total" in response.json()


class TestUsersDirectory:
    async def test_lists_teammates_as_summaries(self, client: AsyncClient, alice, bob) -> None:
        response = await client.get("/api/v1/users", headers=auth(alice))

        assert response.status_code == 200
        items = response.json()["items"]
        assert {item["full_name"] for item in items} >= {"Alice Owner", "Bob Assignee"}
        for item in items:
            # Summaries only: nothing here that should not be public to a
            # logged-in teammate.
            assert set(item) == {"id", "email", "full_name", "initials"}

    async def test_search_by_name(self, client: AsyncClient, alice, bob) -> None:
        response = await client.get("/api/v1/users?search=bob", headers=auth(alice))
        assert [i["full_name"] for i in response.json()["items"]] == ["Bob Assignee"]

    async def test_requires_authentication(self, client: AsyncClient) -> None:
        assert (await client.get("/api/v1/users")).status_code == 401
