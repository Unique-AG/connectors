import httpx
import pytest
import respx
from mcp.types import InputRequiredResult
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.shared.handles import TaskHandle
from office_365_mcp.tools.outlook_update_task import TaskChange, update_task

_LIST_ID = "AAMkSYNTHETIC-list-0001"
_TASK_ID = "AAMkSYNTHETIC-task-0001"
_TASK_URI = TaskHandle(_LIST_ID, _TASK_ID).uri
_LIST_PATH = f"/me/todo/lists/{_LIST_ID}"
_SHARED_LIST = {"id": _LIST_ID, "displayName": "Team launch", "isShared": True}


async def _state_for(client: GraphServiceClient, change: TaskChange) -> str:
    asked: list[str] = []

    async def remember(_question: str, about: str) -> InputRequiredResult:
        asked.append(about)
        return InputRequiredResult(input_requests={}, request_state=about)

    _ = await update_task(client, uri=_TASK_URI, change=change, confirm=remember)
    [about] = asked
    return about


class TestTheQuestionIsBoundToTheChange:
    @pytest.mark.parametrize(
        ("first", "second"),
        [((), None), (("a\nb",), ("a", "b"))],
        ids=["empty-and-omitted", "one-and-two-categories"],
    )
    async def test_two_category_changes_never_share_one_confirmation_state(
        self,
        graph: respx.MockRouter,
        client: GraphServiceClient,
        first: tuple[str, ...] | None,
        second: tuple[str, ...] | None,
    ) -> None:
        _ = graph.get(_LIST_PATH).mock(return_value=httpx.Response(200, json=_SHARED_LIST))
        _ = graph.get(f"{_LIST_PATH}/tasks/{_TASK_ID}").mock(
            return_value=httpx.Response(200, json={"id": _TASK_ID, "title": "Book the venue"})
        )

        states = {
            await _state_for(client, TaskChange(title="Book the venue", categories=categories))
            for categories in (first, second)
        }

        assert len(states) == 2
