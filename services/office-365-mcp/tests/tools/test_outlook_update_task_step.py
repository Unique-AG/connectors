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
from office_365_mcp.shared.seam import WRITE_DESTRUCTIVE_IDEMPOTENT, Confirm
from office_365_mcp.tools import outlook_update_task_step as updater
from office_365_mcp.tools.outlook_update_task_step import update_task_step

_LIST_ID = "AAMkSYNTHETIC-list-0001"

_TASK_ID = "AAMkSYNTHETIC-task-0001"

_STEP_ID = "SYNTHETIC-step-0001"

_STEP_URI = TaskPartHandle("steps", _LIST_ID, _TASK_ID, _STEP_ID).uri

_LIST_PATH = f"/me/todo/lists/{_LIST_ID}"

_STEP_PATH = f"{_LIST_PATH}/tasks/{_TASK_ID}/checklistItems/{_STEP_ID}"

_NOTHING_CHANGED = "Nothing was changed."
_NAMED = "the step 'Call the hotel' of the task 'Plan the offsite'"

_UPDATED = {
    "id": _STEP_ID,
    "displayName": "Book the big room",
    "isChecked": True,
    "checkedDateTime": "2026-11-24T09:30:00Z",
}


def _list(graph: respx.MockRouter, *, is_shared: bool | None = False) -> respx.Route:
    return graph.get(_LIST_PATH).mock(
        return_value=httpx.Response(
            200, json={"id": _LIST_ID, "displayName": "Team", "isShared": is_shared}
        )
    )


def _named(graph: respx.MockRouter) -> None:
    _ = graph.get(f"{_LIST_PATH}/tasks/{_TASK_ID}").mock(
        return_value=httpx.Response(200, json={"id": _TASK_ID, "title": "Plan the offsite"})
    )
    _ = graph.get(_STEP_PATH).mock(
        return_value=httpx.Response(200, json={"id": _STEP_ID, "displayName": "Call the hotel"})
    )


def _patched(graph: respx.MockRouter) -> respx.Route:
    return graph.patch(_STEP_PATH).mock(return_value=httpx.Response(200, json=_UPDATED))


async def _never_asked(question: str, about: str) -> str | None:
    raise AssertionError(f"a private write was put to a person: {question!r} ({about})")


async def _update(
    client: GraphServiceClient,
    *,
    step: str = _STEP_URI,
    text: str | None = None,
    is_checked: bool | None = None,
    confirm: Confirm = _never_asked,
) -> TaskStep:
    answer = await update_task_step(
        client, step=step, text=text, is_checked=is_checked, confirm=confirm
    )
    assert isinstance(answer, TaskStep), "this call was answered with a question"
    return answer


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


class TestWhatItSendsToGraph:
    async def test_it_patches_the_words_and_the_check_and_answers_with_the_step(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _list(graph)
        patch = _patched(graph)

        answer = await _update(client, text="Book the big room", is_checked=True)

        made = cast("Sequence[Call]", graph.calls)
        assert [(call.request.method, call.request.url.path) for call in made] == [
            ("GET", f"/v1.0{_LIST_PATH}"),
            ("PATCH", f"/v1.0{_STEP_PATH}"),
        ]
        assert _sent(patch) == {"displayName": "Book the big room", "isChecked": True}
        assert answer.uri == _STEP_URI
        assert (answer.text, answer.is_checked) == ("Book the big room", True)
        assert answer.checked_at is not None

    async def test_only_the_check_is_sent_when_only_the_check_is_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _list(graph)
        patch = _patched(graph)

        _ = await _update(client, is_checked=False)

        assert _sent(patch) == {"isChecked": False}

    async def test_only_the_words_are_sent_when_only_the_words_are_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _list(graph)
        patch = _patched(graph)

        _ = await _update(client, text="Book the big room")

        assert _sent(patch) == {"displayName": "Book the big room"}


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "step",
        [
            "Book the room",
            TaskHandle(_LIST_ID, _TASK_ID).uri,
            TaskPartHandle("links", _LIST_ID, _TASK_ID, _STEP_ID).uri,
        ],
    )
    async def test_a_bad_step_handle_is_refused_before_any_call(
        self, client: GraphServiceClient, graph: respx.MockRouter, step: str
    ) -> None:
        with pytest.raises(ToolError, match=r"steps\[\]\.uri") as raised:
            _ = await _update(client, step=step, is_checked=True)

        assert "outlook_read_task" in str(raised.value)
        assert _NOTHING_CHANGED in str(raised.value)
        assert not graph.calls

    async def test_a_call_with_nothing_to_change_is_refused_before_any_call(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="nothing to change") as raised:
            _ = await _update(client)

        assert _NOTHING_CHANGED in str(raised.value)
        assert not graph.calls


class TestThePersonBeforeTheWrite:
    async def test_a_private_list_changes_without_a_question(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _list(graph, is_shared=False)
        patch = _patched(graph)

        _ = await _update(client, is_checked=True, confirm=_never_asked)

        assert patch.call_count == 1

    @pytest.mark.parametrize(
        ("text", "is_checked", "opening"),
        [
            (
                None,
                True,
                f"Check off {_NAMED} in the list 'Team'",
            ),
            (
                None,
                False,
                f"Clear the check of {_NAMED} in the list 'Team'",
            ),
            (
                "Call Anna",
                None,
                f"Change {_NAMED} to 'Call Anna' in the list 'Team'",
            ),
            (
                "Call Anna",
                True,
                f"Change {_NAMED} to 'Call Anna' and check it off in the list 'Team'",
            ),
        ],
    )
    async def test_a_shared_list_asks_first_and_the_question_names_the_change(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        text: str | None,
        is_checked: bool | None,
        opening: str,
    ) -> None:
        _ = _list(graph, is_shared=True)
        _named(graph)
        _ = _patched(graph)
        asked: list[str] = []

        async def capture(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _update(client, text=text, is_checked=is_checked, confirm=capture)

        [question] = asked
        assert question.startswith(opening)
        assert question.endswith("They see the change?")

    async def test_a_person_who_declines_keeps_the_step(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _list(graph, is_shared=True)
        _named(graph)
        patch = _patched(graph)

        async def refuses(question: str, about: str) -> str | None:
            assert question
            assert about
            return _NOTHING_CHANGED

        with pytest.raises(ToolError) as raised:
            _ = await _update(client, is_checked=True, confirm=refuses)

        assert str(raised.value) == _NOTHING_CHANGED
        assert patch.call_count == 0

    async def test_a_question_that_a_modern_client_must_answer_is_returned_before_any_write(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _list(graph, is_shared=None)
        _named(graph)
        patch = _patched(graph)

        async def ask_back(question: str, about: str) -> InputRequiredResult:
            assert question
            assert about
            return InputRequiredResult(input_requests={}, request_state="state")

        answer = await update_task_step(client, step=_STEP_URI, is_checked=True, confirm=ask_back)

        assert isinstance(answer, InputRequiredResult)
        assert patch.call_count == 0


class TestWhatItAdvertises:
    async def test_it_is_a_destructive_idempotent_write_that_requires_a_step(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        updater.register(mcp, transport)
        tool = cast("Tool", await mcp.get_tool(updater.TOOL_NAME))

        assert tool.annotations is not None
        assert tool.annotations.model_dump(exclude_none=True, by_alias=True) == (
            WRITE_DESTRUCTIVE_IDEMPOTENT
        )
        assert cast("dict[str, object]", tool.parameters)["required"] == ["step"]


class TestTheQuestionIsBoundToTheNames:
    async def test_a_step_renamed_while_the_person_decides_changes_the_state(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _list(graph, is_shared=True)
        _ = graph.get(f"{_LIST_PATH}/tasks/{_TASK_ID}").mock(
            return_value=httpx.Response(200, json={"id": _TASK_ID, "title": "Plan the offsite"})
        )
        step = graph.get(_STEP_PATH)
        states: list[str] = []
        for name in ("Call the hotel", "Cancel the hotel booking"):
            _ = step.mock(
                return_value=httpx.Response(200, json={"id": _STEP_ID, "displayName": name})
            )

            async def remember(_question: str, about: str) -> InputRequiredResult:
                states.append(about)
                return InputRequiredResult(input_requests={}, request_state=about)

            _ = await update_task_step(client, step=_STEP_URI, is_checked=True, confirm=remember)

        assert states[0] != states[1]
