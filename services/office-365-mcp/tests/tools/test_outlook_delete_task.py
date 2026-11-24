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

from office_365_mcp.shared.handles import TaskHandle
from office_365_mcp.shared.seam import WRITE_DESTRUCTIVE_IDEMPOTENT, Confirm
from office_365_mcp.tools import outlook_delete_task as deleter
from office_365_mcp.tools.outlook_delete_task import DeletedTask, delete_task

_LIST_ID = "AAMkSYNTHETIC-list-0001"

_TASK_ID = "AAMkSYNTHETIC-task-0001"

_URI = TaskHandle(_LIST_ID, _TASK_ID).uri

_LIST_PATH = f"/me/todo/lists/{_LIST_ID}"

_TASK_PATH = f"{_LIST_PATH}/tasks/{_TASK_ID}"

_NOTHING_DELETED = "The task was not deleted."


def _list(graph: respx.MockRouter, *, is_shared: bool | None = False) -> respx.Route:
    return graph.get(_LIST_PATH).mock(
        return_value=httpx.Response(
            200, json={"id": _LIST_ID, "displayName": "Groceries", "isShared": is_shared}
        )
    )


def _task(graph: respx.MockRouter, title: str | None = "Buy milk") -> respx.Route:
    return graph.get(_TASK_PATH).mock(
        return_value=httpx.Response(200, json={"id": _TASK_ID, "title": title})
    )


def _deleted(graph: respx.MockRouter, status: int = 204) -> respx.Route:
    return graph.delete(_TASK_PATH).mock(return_value=httpx.Response(status))


async def _agrees(question: str, about: str) -> str | None:
    assert question
    assert about
    return None


async def _refuses(question: str, about: str) -> str | None:
    assert question
    assert about
    return _NOTHING_DELETED


async def _never_asked(question: str, about: str) -> str | None:
    raise AssertionError(f"a refused delete was put to a person: {question!r} ({about})")


async def _delete(
    client: GraphServiceClient, *, uri: str = _URI, confirm: Confirm = _agrees
) -> DeletedTask:
    answer = await delete_task(client, uri=uri, confirm=confirm)
    assert isinstance(answer, DeletedTask), "this call was answered with a question"
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
    async def test_it_reads_the_list_and_the_title_and_then_deletes_the_task(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _list(graph)
        _ = _task(graph)
        _ = _deleted(graph)

        answer = await _delete(client)

        made = cast("Sequence[Call]", graph.calls)
        assert [(call.request.method, call.request.url.path) for call in made] == [
            ("GET", f"/v1.0{_LIST_PATH}"),
            ("GET", f"/v1.0{_TASK_PATH}"),
            ("DELETE", f"/v1.0{_TASK_PATH}"),
        ]
        assert "$select" not in made[1].request.url.params
        assert (answer.title, answer.deleted) == ("Buy milk", True)

    async def test_a_task_that_is_gone_after_the_read_is_reported_as_deleted(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _list(graph)
        _ = _task(graph)
        _ = _deleted(graph, status=404)

        answer = await _delete(client)

        assert answer.deleted is True


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "uri",
        [
            "Buy milk",
            f"outlook:///tasklists/{_LIST_ID}",
            f"{_URI}/steps/SYNTHETIC-step-0001",
        ],
    )
    async def test_a_bad_handle_is_refused_before_any_call(
        self, client: GraphServiceClient, graph: respx.MockRouter, uri: str
    ) -> None:
        with pytest.raises(ToolError, match="outlook_list_tasks") as raised:
            _ = await _delete(client, uri=uri, confirm=_never_asked)

        assert _NOTHING_DELETED in str(raised.value)
        assert not graph.calls


class TestThePersonBetweenTheReadAndTheDelete:
    async def test_it_asks_even_when_the_list_is_private(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _list(graph, is_shared=False)
        _ = _task(graph)
        _ = _deleted(graph)

        question = await _question_for(client)

        assert question == (
            "Delete the task 'Buy milk' from the list 'Groceries'? Its steps, links, and files go "
            + "with it. This connector cannot undo the delete."
        )

    async def test_the_question_says_that_people_who_share_the_list_lose_the_task(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _list(graph, is_shared=True)
        _ = _task(graph)
        _ = _deleted(graph)

        question = await _question_for(client)

        assert "Other people share this list, and they lose the task too." in question

    async def test_the_question_warns_when_microsoft_does_not_say_whether_the_list_is_shared(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _list(graph, is_shared=None)
        _ = _task(graph)
        _ = _deleted(graph)

        question = await _question_for(client)

        assert "did not report this list as private" in question

    async def test_the_question_names_a_task_with_no_title(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _list(graph)
        _ = _task(graph, title=None)
        _ = _deleted(graph)

        question = await _question_for(client)

        assert question.startswith("Delete the task with no title from the list 'Groceries'?")

    async def test_a_person_who_declines_keeps_the_task(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _list(graph)
        _ = _task(graph)
        delete = _deleted(graph)

        with pytest.raises(ToolError) as raised:
            _ = await _delete(client, confirm=_refuses)

        assert str(raised.value) == _NOTHING_DELETED
        assert delete.call_count == 0

    async def test_a_question_that_a_modern_client_must_answer_is_returned_before_any_delete(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _list(graph)
        _ = _task(graph)
        delete = _deleted(graph)

        async def ask_back(question: str, about: str) -> InputRequiredResult:
            assert question
            assert about
            return InputRequiredResult(input_requests={}, request_state="state")

        answer = await delete_task(client, uri=_URI, confirm=ask_back)

        assert isinstance(answer, InputRequiredResult)
        assert delete.call_count == 0


class TestWhatItAdvertises:
    async def test_it_is_a_destructive_idempotent_write_that_requires_a_uri(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        deleter.register(mcp, transport)
        tool = cast("Tool", await mcp.get_tool(deleter.TOOL_NAME))

        assert tool.annotations is not None
        assert tool.annotations.model_dump(exclude_none=True, by_alias=True) == (
            WRITE_DESTRUCTIVE_IDEMPOTENT
        )
        assert cast("dict[str, object]", tool.parameters)["required"] == ["uri"]
