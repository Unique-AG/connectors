import httpx
import pytest
import respx

from backstop_mcp.features.tasks.tools.get_tasks_for_party import (
    TasksResolvedResponse,
    get_tasks_for_party,
)
from backstop_mcp.server.tools import TOOLS
from tests.features.party_resolver.helpers import ctx_never_elicit
from tests.helpers import BASE_URL, recorded_requests, tool_client
from tests.server.tools.helpers import object_dict, object_list, tool_model, tool_payload

_ORG_ID = "341764767"


def tenant(name: str) -> str:
    return f"{BASE_URL}/{name}"


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


class TestGetTasksForParty:
    def test_is_registered_and_names_the_bean_pair(self) -> None:
        assert get_tasks_for_party in TOOLS
        doc = get_tasks_for_party.__doc__ or ""
        assert "OrganizationBean" in doc
        assert "entityType" in doc
        assert "entityId" in doc

    @pytest.mark.asyncio
    @respx.mock
    async def test_sends_both_entity_filters_with_organization_bean(self) -> None:
        base_url = tenant("tk-pin")
        tasks = respx.get(f"{base_url}/tasks").mock(
            return_value=_page(
                _task("t1", title="Call back", status="Open"),
                _task("t2", title="Done item", status="Completed"),
            )
        )

        async with tool_client(base_url) as client:
            result = tool_model(
                await get_tasks_for_party(
                    ctx_never_elicit(),
                    search_type="organizations",
                    party_id=_ORG_ID,
                    client=client,
                ),
                TasksResolvedResponse,
            )

        assert tasks.call_count == 1
        params = recorded_requests(tasks.calls)[0].url.params
        assert params["filter[entityType][eq]"] == "OrganizationBean"
        assert params["filter[entityId][eq]"] == _ORG_ID
        assert "filter[status]" not in params
        assert result.total == 2
        assert result.open_count == 1
        assert result.completed_count == 1
        rows = [object_dict(item) for item in object_list(tool_payload(result)["tasks"])]
        assert [item["id"] for item in rows] == ["t1", "t2"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_open_status_is_client_side(self) -> None:
        base_url = tenant("tk-open")
        respx.get(f"{base_url}/tasks").mock(
            return_value=_page(
                _task("t1", title="Call back", status="Open"),
                _task("t2", title="Done item", completed=True),
            )
        )

        async with tool_client(base_url) as client:
            result = tool_model(
                await get_tasks_for_party(
                    ctx_never_elicit(),
                    search_type="organizations",
                    party_id=_ORG_ID,
                    status="open",
                    client=client,
                ),
                TasksResolvedResponse,
            )

        rows = [object_dict(item) for item in object_list(tool_payload(result)["tasks"])]
        assert [item["id"] for item in rows] == ["t1"]
        assert result.total == 2
        assert result.open_count == 1
