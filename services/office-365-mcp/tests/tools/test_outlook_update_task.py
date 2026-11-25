from datetime import date

import httpx
import pytest
import respx
from mcp.types import InputRequiredResult
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.shared.handles import TaskHandle
from office_365_mcp.shared.outlook.tasks import TaskRepeat
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


class TestTheQuestionNamesTheSeries:
    @pytest.mark.parametrize(
        ("repeat", "spoken"),
        [
            (TaskRepeat(every="day", interval=30), "repeats every 30 days"),
            (
                TaskRepeat(every="week", weekdays=("monday", "thursday")),
                "repeats every week on monday, thursday",
            ),
        ],
        ids=["interval", "weekdays"],
    )
    async def test_it_states_the_interval_and_the_weekdays(
        self,
        graph: respx.MockRouter,
        client: GraphServiceClient,
        repeat: TaskRepeat,
        spoken: str,
    ) -> None:
        _ = graph.get(_LIST_PATH).mock(return_value=httpx.Response(200, json=_SHARED_LIST))
        _ = graph.get(f"{_LIST_PATH}/tasks/{_TASK_ID}").mock(
            return_value=httpx.Response(200, json={"id": _TASK_ID, "title": "Water the plants"})
        )
        asked: list[str] = []

        async def remember(question: str, about: str) -> InputRequiredResult:
            asked.append(question)
            return InputRequiredResult(input_requests={}, request_state=about)

        _ = await update_task(
            client,
            uri=_TASK_URI,
            change=TaskChange(due_date=date(2026, 11, 30), repeat=repeat),
            confirm=remember,
        )

        [question] = asked
        assert f"{spoken} from 2026-11-30" in question


class TestTheQuestionIsBoundToTheSeriesStart:
    async def test_a_due_date_that_changes_while_the_person_decides_changes_the_state(
        self, graph: respx.MockRouter, client: GraphServiceClient
    ) -> None:
        _ = graph.get(_LIST_PATH).mock(return_value=httpx.Response(200, json=_SHARED_LIST))
        read = graph.get(f"{_LIST_PATH}/tasks/{_TASK_ID}")
        states: list[str] = []
        for day in ("2026-11-30T00:00:00", "2026-12-01T00:00:00"):
            task = {
                "id": _TASK_ID,
                "title": "Water the plants",
                "dueDateTime": {"dateTime": day, "timeZone": "UTC"},
            }
            _ = read.mock(return_value=httpx.Response(200, json=task))
            states.append(await _state_for(client, TaskChange(repeat=TaskRepeat(every="week"))))

        assert states[0] != states[1]
