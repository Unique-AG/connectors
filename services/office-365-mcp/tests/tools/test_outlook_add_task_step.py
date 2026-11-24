import json
from collections.abc import Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from mcp.types import InputRequiredResult
from msgraph.graph_service_client import GraphServiceClient
from respx.models import Call

from office_365_mcp.shared.handles import TaskHandle, TaskPartHandle
from office_365_mcp.shared.outlook.tasks import TaskStep
from office_365_mcp.shared.seam import WRITE_ADDITIVE, Confirm
from office_365_mcp.tools import outlook_add_task_step as adder
from office_365_mcp.tools.outlook_add_task_step import add_task_step

_LIST_ID = "AAMkSYNTHETIC-list-0001"

_TASK_ID = "AAMkSYNTHETIC-task-0001"

_STEP_ID = "SYNTHETIC-step-0001"

_URI = TaskHandle(_LIST_ID, _TASK_ID).uri

_LIST_PATH = f"/me/todo/lists/{_LIST_ID}"

_STEPS_PATH = f"{_LIST_PATH}/tasks/{_TASK_ID}/checklistItems"

_NOTHING_ADDED = "No step was added."

_CREATED: dict[str, object] = {
    "id": _STEP_ID,
    "displayName": "Book the room",
    "isChecked": False,
    "createdDateTime": "2026-11-24T08:00:00Z",
}


def _list(graph: respx.MockRouter, *, is_shared: bool | None = False) -> respx.Route:
    return graph.get(_LIST_PATH).mock(
        return_value=httpx.Response(
            200, json={"id": _LIST_ID, "displayName": "Team", "isShared": is_shared}
        )
    )


def _posted(graph: respx.MockRouter, created: dict[str, object] = _CREATED) -> respx.Route:
    return graph.post(_STEPS_PATH).mock(return_value=httpx.Response(201, json=created))


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


async def _never_asked(question: str, about: str) -> str | None:
    raise AssertionError(f"a private write was put to a person: {question!r} ({about})")


async def _add(
    client: GraphServiceClient,
    *,
    uri: str = _URI,
    text: str = "Book the room",
    is_checked: bool = False,
    confirm: Confirm = _never_asked,
) -> TaskStep:
    answer = await add_task_step(client, uri=uri, text=text, is_checked=is_checked, confirm=confirm)
    assert isinstance(answer, TaskStep), "this call was answered with a question"
    return answer


class TestWhatItSendsToGraph:
    async def test_it_posts_the_words_and_the_check_of_the_step(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _list(graph)
        post = _posted(graph)

        answer = await _add(client, text="Book the room", is_checked=True)

        made = cast("Sequence[Call]", graph.calls)
        assert [(call.request.method, call.request.url.path) for call in made] == [
            ("GET", f"/v1.0{_LIST_PATH}"),
            ("POST", f"/v1.0{_STEPS_PATH}"),
        ]
        sent = _sent(post)
        assert sent == {"displayName": "Book the room", "isChecked": True}
        assert answer == TaskStep(
            uri=TaskPartHandle("steps", _LIST_ID, _TASK_ID, _STEP_ID).uri,
            text="Book the room",
            is_checked=False,
            checked_at=None,
        )

    async def test_a_new_step_is_not_checked_by_default(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _list(graph)
        post = _posted(graph)

        _ = await _add(client)

        sent = _sent(post)
        assert sent["isChecked"] is False


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "uri", ["Buy milk", f"outlook:///tasklists/{_LIST_ID}", f"{_URI}/steps/{_STEP_ID}"]
    )
    async def test_a_bad_handle_is_refused_before_any_call(
        self, client: GraphServiceClient, graph: respx.MockRouter, uri: str
    ) -> None:
        with pytest.raises(ToolError, match="outlook_list_tasks") as raised:
            _ = await _add(client, uri=uri)

        assert _NOTHING_ADDED in str(raised.value)
        assert not graph.calls


class TestThePersonBeforeTheWrite:
    async def test_a_private_list_gets_the_step_without_a_question(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _list(graph, is_shared=False)
        post = _posted(graph)

        _ = await _add(client, confirm=_never_asked)

        assert post.call_count == 1

    @pytest.mark.parametrize("is_shared", [True, None])
    async def test_a_list_that_reaches_others_asks_first_and_names_the_step(
        self, client: GraphServiceClient, graph: respx.MockRouter, is_shared: bool | None
    ) -> None:
        _ = _list(graph, is_shared=is_shared)
        _ = _posted(graph)
        asked: list[str] = []

        async def capture(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _add(client, confirm=capture)

        [question] = asked
        assert question.startswith("Add the step 'Book the room' to a task in the list 'Team'")

    async def test_a_person_who_declines_gets_no_new_step(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _list(graph, is_shared=True)
        post = _posted(graph)

        async def refuses(question: str, about: str) -> str | None:
            assert question
            assert about
            return _NOTHING_ADDED

        with pytest.raises(ToolError) as raised:
            _ = await _add(client, confirm=refuses)

        assert str(raised.value) == _NOTHING_ADDED
        assert post.call_count == 0

    async def test_a_question_that_a_modern_client_must_answer_is_returned_before_any_write(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _list(graph, is_shared=True)
        post = _posted(graph)

        async def ask_back(question: str, about: str) -> InputRequiredResult:
            assert question
            assert about
            return InputRequiredResult(input_requests={}, request_state="state")

        answer = await add_task_step(client, uri=_URI, text="Book the room", confirm=ask_back)

        assert isinstance(answer, InputRequiredResult)
        assert post.call_count == 0


class TestWhatItAdvertises:
    async def test_it_is_an_additive_write_that_requires_a_task_and_words(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        adder.register(mcp, transport)
        tool = cast("Tool", await mcp.get_tool(adder.TOOL_NAME))

        assert tool.annotations is not None
        assert tool.annotations.model_dump(exclude_none=True, by_alias=True) == WRITE_ADDITIVE
        assert cast("dict[str, object]", tool.parameters)["required"] == ["uri", "text"]
