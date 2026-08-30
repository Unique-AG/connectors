import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.tasks import PartyTasksResponse
from tests.features.tasks.conftest import make_get_tasks_for_party_query
from tests.helpers import BASE_URL, recorded_requests

_ORG_ID = "341764767"


def _page(*items: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json={"data": list(items), "links": {"next": None}})


def _task(
    task_id: str,
    *,
    title: str,
    status: str | None = None,
    completed: bool | None = None,
) -> dict[str, object]:
    attributes: dict[str, object] = {"title": title}
    if status is not None:
        attributes["status"] = status
    if completed is not None:
        attributes["completed"] = completed
    return {"id": task_id, "type": "tasks", "attributes": attributes}


class TestGetTasksForPartyQuery:
    @pytest.mark.asyncio
    @respx.mock
    async def test_walks_tasks_with_both_entity_filters_and_splits_open(
        self, client: BackstopClient
    ) -> None:
        route = respx.get(f"{BASE_URL}/tasks").mock(
            return_value=_page(
                _task("t1", title="Call back", status="Open"),
                _task("t2", title="Done item", completed=True),
            )
        )

        fetched = await make_get_tasks_for_party_query(client).run(
            search_type="organizations",
            entity_id=_ORG_ID,
            status="open",
        )

        assert isinstance(fetched, PartyTasksResponse)
        params = recorded_requests(route.calls)[0].url.params
        assert params["filter[entityType][eq]"] == "OrganizationBean"
        assert params["filter[entityId][eq]"] == _ORG_ID
        assert "filter[status]" not in params
        assert [row.id for row in fetched.tasks] == ["t1"]
        assert fetched.total == 2
        assert fetched.open_count == 1
        assert fetched.completed_count == 1
        assert fetched.scan_truncated is False
