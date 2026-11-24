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
from office_365_mcp.shared.seam import WRITE_DESTRUCTIVE_IDEMPOTENT, Confirm
from office_365_mcp.tools import outlook_delete_task_step as deleter
from office_365_mcp.tools.outlook_delete_task_step import DeletedTaskStep, delete_task_step

_LIST_ID = "AAMkSYNTHETIC-list-0001"

_TASK_ID = "AAMkSYNTHETIC-task-0001"

_STEP_ID = "SYNTHETIC-step-0001"

_STEP_URI = TaskPartHandle("steps", _LIST_ID, _TASK_ID, _STEP_ID).uri

_LIST_PATH = f"/me/todo/lists/{_LIST_ID}"

_TASK_PATH = f"{_LIST_PATH}/tasks/{_TASK_ID}"

_STEP_PATH = f"{_TASK_PATH}/checklistItems/{_STEP_ID}"

_NOTHING_DELETED = "The step was not deleted."


def _list(graph: respx.MockRouter, *, is_shared: bool | None = False) -> respx.Route:
    return graph.get(_LIST_PATH).mock(
        return_value=httpx.Response(
            200, json={"id": _LIST_ID, "displayName": "Team", "isShared": is_shared}
        )
    )


def _task(graph: respx.MockRouter, title: str | None = "Plan the offsite") -> respx.Route:
    return graph.get(_TASK_PATH).mock(
        return_value=httpx.Response(200, json={"id": _TASK_ID, "title": title})
    )


def _step(graph: respx.MockRouter, text: str | None = "Book the room") -> respx.Route:
    return graph.get(_STEP_PATH).mock(
        return_value=httpx.Response(200, json={"id": _STEP_ID, "displayName": text})
    )


def _deleted(graph: respx.MockRouter, status: int = 204) -> respx.Route:
    return graph.delete(_STEP_PATH).mock(return_value=httpx.Response(status))


def _all_found(graph: respx.MockRouter, *, is_shared: bool | None = False) -> respx.Route:
    _ = _list(graph, is_shared=is_shared)
    _ = _task(graph)
    _ = _step(graph)
    return _deleted(graph)


async def _agrees(question: str, about: str) -> str | None:
    assert question
    assert about
    return None


async def _never_asked(question: str, about: str) -> str | None:
    raise AssertionError(f"a refused delete was put to a person: {question!r} ({about})")


async def _delete(
    client: GraphServiceClient, *, step: str = _STEP_URI, confirm: Confirm = _agrees
) -> DeletedTaskStep:
    answer = await delete_task_step(client, step=step, confirm=confirm)
    assert isinstance(answer, DeletedTaskStep), "this call was answered with a question"
    return answer


async def _question_for(client: GraphServiceClient) -> str:
    asked: list[str] = []

    async def capture(question: str, about: str) -> str | None:
        assert about
        asked.append(question)
        return None

    _ = await _delete(client, confirm=capture)
    [question] = asked
    return question


class TestWhatItSendsToGraph:
    async def test_it_reads_the_list_the_task_and_the_step_and_then_deletes_the_step(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _all_found(graph)

        answer = await _delete(client)

        made = cast("Sequence[Call]", graph.calls)
        assert [(call.request.method, call.request.url.path) for call in made] == [
            ("GET", f"/v1.0{_LIST_PATH}"),
            ("GET", f"/v1.0{_TASK_PATH}"),
            ("GET", f"/v1.0{_STEP_PATH}"),
            ("DELETE", f"/v1.0{_STEP_PATH}"),
        ]
        assert made[1].request.url.params["$select"] == "id,title"
        assert made[2].request.url.params["$select"] == "id,displayName"
        assert (answer.text, answer.deleted) == ("Book the room", True)

    async def test_a_step_that_is_gone_after_the_read_is_reported_as_deleted(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _list(graph)
        _ = _task(graph)
        _ = _step(graph)
        _ = _deleted(graph, status=404)

        answer = await _delete(client)

        assert answer.deleted is True


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "step",
        [
            "Book the room",
            TaskHandle(_LIST_ID, _TASK_ID).uri,
            TaskPartHandle("attachments", _LIST_ID, _TASK_ID, _STEP_ID).uri,
        ],
    )
    async def test_a_bad_step_handle_is_refused_before_any_call(
        self, client: GraphServiceClient, graph: respx.MockRouter, step: str
    ) -> None:
        with pytest.raises(ToolError, match=r"steps\[\]\.uri") as raised:
            _ = await _delete(client, step=step, confirm=_never_asked)

        assert "outlook_read_task" in str(raised.value)
        assert _NOTHING_DELETED in str(raised.value)
        assert not graph.calls


class TestThePersonBetweenTheReadAndTheDelete:
    async def test_it_asks_even_when_the_list_is_private_and_names_the_step_and_the_task(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _all_found(graph, is_shared=False)

        question = await _question_for(client)

        assert question == (
            "Delete the step 'Book the room' from the task 'Plan the offsite'? This connector "
            + "cannot undo the delete."
        )

    async def test_the_question_says_that_people_who_share_the_list_lose_the_step(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _all_found(graph, is_shared=True)

        question = await _question_for(client)

        assert "Other people share the list of this task, and they lose the step too." in question

    async def test_a_person_who_declines_keeps_the_step(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        delete = _all_found(graph)

        async def refuses(question: str, about: str) -> str | None:
            assert question
            assert about
            return _NOTHING_DELETED

        with pytest.raises(ToolError) as raised:
            _ = await _delete(client, confirm=refuses)

        assert str(raised.value) == _NOTHING_DELETED
        assert delete.call_count == 0

    async def test_a_question_that_a_modern_client_must_answer_is_returned_before_any_delete(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        delete = _all_found(graph)

        async def ask_back(question: str, about: str) -> InputRequiredResult:
            assert question
            assert about
            return InputRequiredResult(input_requests={}, request_state="state")

        answer = await delete_task_step(client, step=_STEP_URI, confirm=ask_back)

        assert isinstance(answer, InputRequiredResult)
        assert delete.call_count == 0


class TestWhatItAdvertises:
    async def test_it_is_a_destructive_idempotent_write_that_requires_a_step(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        deleter.register(mcp, transport)
        tool = cast("Tool", await mcp.get_tool(deleter.TOOL_NAME))

        assert tool.annotations is not None
        assert tool.annotations.model_dump(exclude_none=True, by_alias=True) == (
            WRITE_DESTRUCTIVE_IDEMPOTENT
        )
        assert cast("dict[str, object]", tool.parameters)["required"] == ["step"]
