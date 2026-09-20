"""Task endpoints, end to end."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from tests.conftest import auth, user_id_of

pytestmark = [pytest.mark.integration]


def iso(offset: timedelta) -> str:
    return (datetime.now(UTC) + offset).isoformat().replace("+00:00", "Z")


async def create_task(
    client: AsyncClient, headers: dict[str, str], **payload: object
) -> dict[str, Any]:
    body = {"title": "A perfectly reasonable task"} | payload
    response = await client.post("/api/v1/tasks", headers=auth(headers), json=body)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


class TestCreate:
    async def test_creates_an_open_task_owned_by_the_caller(
        self, client: AsyncClient, alice
    ) -> None:
        response = await client.post(
            "/api/v1/tasks",
            headers=auth(alice),
            json={
                "title": "  Write   the   integration tests  ",
                "description": "  and trim this  ",
                "priority": "high",
                "due_date": iso(timedelta(days=10)),
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["title"] == "Write the integration tests"
        assert body["description"] == "and trim this"
        assert body["status"] == "todo"
        assert body["priority"] == "high"
        assert body["completed_at"] is None
        assert body["is_overdue"] is False
        assert body["owner"]["id"] == user_id_of(alice)
        assert body["assignee"] is None
        # Capability flags let the UI disable what it may not do.
        assert body["can_edit"] is True
        assert body["can_change_status"] is True

    async def test_can_be_created_pre_assigned(self, client: AsyncClient, alice, bob) -> None:
        body = await create_task(client, alice, assignee_id=user_id_of(bob))
        assert body["assignee"]["id"] == user_id_of(bob)
        assert body["assignee"]["full_name"] == "Bob Assignee"

    async def test_rejects_a_deadline_in_the_past(self, client: AsyncClient, alice) -> None:
        response = await client.post(
            "/api/v1/tasks",
            headers=auth(alice),
            json={"title": "Backdated task", "due_date": iso(timedelta(days=-1))},
        )
        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"

    async def test_naive_datetime_is_interpreted_as_utc(
        self, client: AsyncClient, alice
    ) -> None:
        """A timestamp with no offset must not depend on the server timezone."""
        future = (datetime.now(UTC) + timedelta(days=5)).replace(tzinfo=None)
        body = await create_task(client, alice, due_date=future.isoformat())
        assert body["due_date"].endswith("Z") or "+00:00" in body["due_date"]

    async def test_unknown_assignee_is_a_404(self, client: AsyncClient, alice) -> None:
        response = await client.post(
            "/api/v1/tasks",
            headers=auth(alice),
            json={
                "title": "Assign to a ghost",
                "assignee_id": "00000000-0000-4000-8000-000000000000",
            },
        )
        assert response.status_code == 404

    async def test_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/tasks", json={"title": "Anonymous task"})
        assert response.status_code == 401

    @pytest.mark.parametrize(
        "payload",
        [
            {"title": "no"},
            {"title": ""},
            {"title": "x" * 201},
            {"title": "Valid title", "priority": "catastrophic"},
            {"title": "Valid title", "status": "invented"},
            {"title": "Valid title", "due_date": "not-a-date"},
            {"title": "Valid title", "assignee_id": "not-a-uuid"},
        ],
    )
    async def test_rejects_invalid_payloads(
        self, client: AsyncClient, alice, payload: dict
    ) -> None:
        response = await client.post("/api/v1/tasks", headers=auth(alice), json=payload)
        assert response.status_code == 422


class TestRead:
    async def test_owner_reads_their_task(self, client: AsyncClient, alice) -> None:
        created = await create_task(client, alice)
        response = await client.get(f"/api/v1/tasks/{created['id']}", headers=auth(alice))
        assert response.status_code == 200
        assert response.json()["id"] == created["id"]

    async def test_assignee_reads_but_cannot_edit(
        self, client: AsyncClient, alice, bob
    ) -> None:
        created = await create_task(client, alice, assignee_id=user_id_of(bob))

        response = await client.get(f"/api/v1/tasks/{created['id']}", headers=auth(bob))
        assert response.status_code == 200
        body = response.json()
        assert body["can_edit"] is False
        assert body["can_change_status"] is True

    async def test_outsider_gets_404_not_403(self, client: AsyncClient, alice, carol) -> None:
        """404 for a task that exists but is not yours.

        A 403 would confirm the id is real, which is an information leak on
        an endpoint that takes a guessable-looking identifier.
        """
        created = await create_task(client, alice)
        response = await client.get(f"/api/v1/tasks/{created['id']}", headers=auth(carol))
        assert response.status_code == 404

    async def test_unknown_id_is_404(self, client: AsyncClient, alice) -> None:
        response = await client.get(
            "/api/v1/tasks/00000000-0000-4000-8000-000000000000", headers=auth(alice)
        )
        assert response.status_code == 404

    async def test_malformed_id_is_422(self, client: AsyncClient, alice) -> None:
        response = await client.get("/api/v1/tasks/not-a-uuid", headers=auth(alice))
        assert response.status_code == 422


class TestUpdate:
    async def test_patches_only_what_was_sent(self, client: AsyncClient, alice) -> None:
        created = await create_task(
            client,
            alice,
            title="Original title",
            description="Original description",
            priority="low",
            due_date=iso(timedelta(days=10)),
        )

        response = await client.patch(
            f"/api/v1/tasks/{created['id']}",
            headers=auth(alice),
            json={"priority": "urgent"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["priority"] == "urgent"
        assert body["title"] == "Original title"
        assert body["description"] == "Original description"
        assert body["due_date"] == created["due_date"]

    async def test_explicit_null_clears_the_deadline(self, client: AsyncClient, alice) -> None:
        """The three-state PATCH: omitted vs null vs value."""
        created = await create_task(client, alice, due_date=iso(timedelta(days=10)))
        assert created["due_date"] is not None

        response = await client.patch(
            f"/api/v1/tasks/{created['id']}",
            headers=auth(alice),
            json={"due_date": None},
        )
        assert response.status_code == 200
        assert response.json()["due_date"] is None

    async def test_omitting_the_deadline_leaves_it_untouched(
        self, client: AsyncClient, alice
    ) -> None:
        created = await create_task(client, alice, due_date=iso(timedelta(days=10)))
        response = await client.patch(
            f"/api/v1/tasks/{created['id']}",
            headers=auth(alice),
            json={"title": "Only the title changes"},
        )
        assert response.json()["due_date"] == created["due_date"]

    async def test_empty_patch_is_rejected(self, client: AsyncClient, alice) -> None:
        created = await create_task(client, alice)
        response = await client.patch(
            f"/api/v1/tasks/{created['id']}", headers=auth(alice), json={}
        )
        assert response.status_code == 422
        assert "at least one field" in response.text

    @pytest.mark.parametrize("field", ["title", "description", "priority", "status"])
    async def test_null_on_a_non_nullable_field_is_rejected(
        self, client: AsyncClient, alice, field: str
    ) -> None:
        # Answering 422 is more useful than silently ignoring the field.
        created = await create_task(client, alice)
        response = await client.patch(
            f"/api/v1/tasks/{created['id']}", headers=auth(alice), json={field: None}
        )
        assert response.status_code == 422
        assert f"'{field}' cannot be null" in response.text

    async def test_assignee_cannot_rewrite_content(
        self, client: AsyncClient, alice, bob
    ) -> None:
        created = await create_task(client, alice, assignee_id=user_id_of(bob))
        response = await client.patch(
            f"/api/v1/tasks/{created['id']}",
            headers=auth(bob),
            json={"title": "Hijacked by the assignee"},
        )
        assert response.status_code == 403
        assert response.json()["code"] == "permission_denied"

    async def test_assignee_may_change_the_status(
        self, client: AsyncClient, alice, bob
    ) -> None:
        created = await create_task(client, alice, assignee_id=user_id_of(bob))
        response = await client.patch(
            f"/api/v1/tasks/{created['id']}",
            headers=auth(bob),
            json={"status": "in_progress"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "in_progress"

    async def test_outsider_gets_404(self, client: AsyncClient, alice, carol) -> None:
        created = await create_task(client, alice)
        response = await client.patch(
            f"/api/v1/tasks/{created['id']}",
            headers=auth(carol),
            json={"title": "Hijacked by a stranger"},
        )
        assert response.status_code == 404

    async def test_reassign_and_complete_in_a_single_request(
        self, client: AsyncClient, alice, bob
    ) -> None:
        created = await create_task(client, alice)
        response = await client.patch(
            f"/api/v1/tasks/{created['id']}",
            headers=auth(alice),
            json={"assignee_id": user_id_of(bob), "status": "done"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["assignee"]["id"] == user_id_of(bob)
        assert body["status"] == "done"
        assert body["completed_at"] is not None


class TestLifecycle:
    async def test_complete_then_reopen(self, client: AsyncClient, alice) -> None:
        created = await create_task(client, alice)

        done = await client.post(f"/api/v1/tasks/{created['id']}/complete", headers=auth(alice))
        assert done.status_code == 200
        assert done.json()["status"] == "done"
        assert done.json()["completed_at"] is not None

        reopened = await client.post(
            f"/api/v1/tasks/{created['id']}/reopen", headers=auth(alice)
        )
        assert reopened.status_code == 200
        assert reopened.json()["status"] == "todo"
        # The completion timestamp must not survive; the database check
        # constraint would reject it too.
        assert reopened.json()["completed_at"] is None

    async def test_completing_twice_is_a_409(self, client: AsyncClient, alice) -> None:
        created = await create_task(client, alice)
        await client.post(f"/api/v1/tasks/{created['id']}/complete", headers=auth(alice))

        response = await client.post(
            f"/api/v1/tasks/{created['id']}/complete", headers=auth(alice)
        )
        assert response.status_code == 409
        assert response.json()["code"] == "conflict"

    async def test_reopening_an_open_task_is_a_409(self, client: AsyncClient, alice) -> None:
        created = await create_task(client, alice)
        response = await client.post(
            f"/api/v1/tasks/{created['id']}/reopen", headers=auth(alice)
        )
        assert response.status_code == 409

    async def test_assignee_can_complete(self, client: AsyncClient, alice, bob) -> None:
        created = await create_task(client, alice, assignee_id=user_id_of(bob))
        response = await client.post(
            f"/api/v1/tasks/{created['id']}/complete", headers=auth(bob)
        )
        assert response.status_code == 200

    async def test_outsider_cannot_complete(self, client: AsyncClient, alice, carol) -> None:
        created = await create_task(client, alice)
        response = await client.post(
            f"/api/v1/tasks/{created['id']}/complete", headers=auth(carol)
        )
        assert response.status_code == 404

    async def test_completing_an_overdue_task_clears_the_flag(
        self, client: AsyncClient, alice
    ) -> None:
        created = await create_task(client, alice, due_date=iso(timedelta(days=1)))
        # Push the deadline into the past via the repository-level rule:
        # completing it makes ``is_overdue`` false regardless.
        response = await client.post(
            f"/api/v1/tasks/{created['id']}/complete", headers=auth(alice)
        )
        assert response.json()["is_overdue"] is False


class TestAssignment:
    async def test_owner_assigns_and_unassigns(self, client: AsyncClient, alice, bob) -> None:
        created = await create_task(client, alice)

        assigned = await client.put(
            f"/api/v1/tasks/{created['id']}/assignee",
            headers=auth(alice),
            json={"assignee_id": user_id_of(bob)},
        )
        assert assigned.status_code == 200
        assert assigned.json()["assignee"]["id"] == user_id_of(bob)

        unassigned = await client.put(
            f"/api/v1/tasks/{created['id']}/assignee",
            headers=auth(alice),
            json={"assignee_id": None},
        )
        assert unassigned.status_code == 200
        assert unassigned.json()["assignee"] is None

    async def test_assignee_cannot_reassign(
        self, client: AsyncClient, alice, bob, carol
    ) -> None:
        created = await create_task(client, alice, assignee_id=user_id_of(bob))
        response = await client.put(
            f"/api/v1/tasks/{created['id']}/assignee",
            headers=auth(bob),
            json={"assignee_id": user_id_of(carol)},
        )
        assert response.status_code == 403

    async def test_assigning_makes_the_task_visible_to_the_assignee(
        self, client: AsyncClient, alice, bob
    ) -> None:
        created = await create_task(client, alice)

        before = await client.get(f"/api/v1/tasks/{created['id']}", headers=auth(bob))
        assert before.status_code == 404

        await client.put(
            f"/api/v1/tasks/{created['id']}/assignee",
            headers=auth(alice),
            json={"assignee_id": user_id_of(bob)},
        )
        after = await client.get(f"/api/v1/tasks/{created['id']}", headers=auth(bob))
        assert after.status_code == 200


class TestDelete:
    async def test_owner_deletes_and_gets_an_empty_204(
        self, client: AsyncClient, alice
    ) -> None:
        created = await create_task(client, alice)

        response = await client.delete(f"/api/v1/tasks/{created['id']}", headers=auth(alice))
        assert response.status_code == 204
        # A 204 with a body breaks strict HTTP clients.
        assert response.content == b""

        assert (
            await client.get(f"/api/v1/tasks/{created['id']}", headers=auth(alice))
        ).status_code == 404

    async def test_assignee_cannot_delete(self, client: AsyncClient, alice, bob) -> None:
        created = await create_task(client, alice, assignee_id=user_id_of(bob))
        response = await client.delete(f"/api/v1/tasks/{created['id']}", headers=auth(bob))
        assert response.status_code == 403

    async def test_outsider_gets_404(self, client: AsyncClient, alice, carol) -> None:
        created = await create_task(client, alice)
        response = await client.delete(f"/api/v1/tasks/{created['id']}", headers=auth(carol))
        assert response.status_code == 404

    async def test_deleting_twice_is_404(self, client: AsyncClient, alice) -> None:
        created = await create_task(client, alice)
        await client.delete(f"/api/v1/tasks/{created['id']}", headers=auth(alice))
        response = await client.delete(f"/api/v1/tasks/{created['id']}", headers=auth(alice))
        assert response.status_code == 404


class TestBackgroundProcessing:
    async def test_assignment_publishes_a_domain_event(
        self, client: AsyncClient, container, alice, bob
    ) -> None:
        """Events are recorded only after the transaction commits.

        In tests Celery is disabled, so the publisher is the in-memory one and
        the dispatch can be asserted without a broker.
        """
        publisher = container.event_publisher
        publisher.clear()

        await create_task(client, alice, assignee_id=user_id_of(bob))

        assert [event.name for event in publisher.published] == ["TaskAssigned"]

    async def test_a_rejected_write_publishes_nothing(
        self, client: AsyncClient, container, alice
    ) -> None:
        publisher = container.event_publisher
        publisher.clear()

        response = await client.post(
            "/api/v1/tasks",
            headers=auth(alice),
            json={
                "title": "Assign to a ghost",
                "assignee_id": "00000000-0000-4000-8000-000000000000",
            },
        )

        assert response.status_code == 404
        # No notification for work that was never created.
        assert publisher.published == []

    async def test_completion_publishes_an_event(
        self, client: AsyncClient, container, alice, bob
    ) -> None:
        created = await create_task(client, alice, assignee_id=user_id_of(bob))
        publisher = container.event_publisher
        publisher.clear()

        await client.post(f"/api/v1/tasks/{created['id']}/complete", headers=auth(bob))

        assert [event.name for event in publisher.published] == ["TaskCompleted"]
