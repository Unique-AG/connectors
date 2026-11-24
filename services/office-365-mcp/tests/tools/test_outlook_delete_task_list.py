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

from office_365_mcp.shared.seam import WRITE_DESTRUCTIVE_IDEMPOTENT, Confirm
from office_365_mcp.tools import outlook_delete_task_list as deleter
from office_365_mcp.tools.outlook_delete_task_list import DeletedTaskList, delete_task_list

_LIST_ID = "list-0001"

_URI = f"outlook:///tasklists/{_LIST_ID}"

_PATH = f"/me/todo/lists/{_LIST_ID}"

_NOTHING_DELETED = "Nothing was deleted."

_ASKED = (
    "Delete the task list 'Launch' and every task in it? This connector cannot undo the delete."
)


def _read(
    graph: respx.MockRouter,
    *,
    is_shared: bool | None = False,
    is_owner: bool | None = True,
    well_known: str = "none",
) -> respx.Route:
    payload = {
        "id": _LIST_ID,
        "displayName": "Launch",
        "isShared": is_shared,
        "isOwner": is_owner,
        "wellknownListName": well_known,
    }
    return graph.get(_PATH).mock(return_value=httpx.Response(200, json=payload))


def _deleted(graph: respx.MockRouter, status: int = 204) -> respx.Route:
    return graph.delete(_PATH).mock(return_value=httpx.Response(status))


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
    client: GraphServiceClient, *, task_list: str = _URI, confirm: Confirm = _agrees
) -> DeletedTaskList:
    answer = await delete_task_list(client, task_list=task_list, confirm=confirm)
    assert isinstance(answer, DeletedTaskList), "this call was answered with a question"
    return answer


async def _question_for(client: GraphServiceClient) -> str:
    asked: list[tuple[str, str]] = []

    async def capture(question: str, about: str) -> str | None:
        asked.append((question, about))
        return None

    _ = await _delete(client, confirm=capture)
    [(question, about)] = asked
    assert about
    return question


class TestWhatItSendsToGraph:
    async def test_it_reads_the_list_and_deletes_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _read(graph)
        _ = _deleted(graph)

        answer = await _delete(client)

        made = cast("Sequence[Call]", graph.calls)
        assert [(call.request.method, call.request.url.path) for call in made] == [
            ("GET", f"/v1.0{_PATH}"),
            ("DELETE", f"/v1.0{_PATH}"),
        ]
        assert made[0].request.url.params["$select"] == (
            "id,displayName,isShared,isOwner,wellknownListName"
        )
        assert (answer.uri, answer.name, answer.deleted) == (_URI, "Launch", True)

    async def test_a_list_that_is_gone_after_the_read_is_reported_as_deleted(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _read(graph)
        _ = _deleted(graph, status=404)

        answer = await _delete(client)

        assert answer.deleted is True


class TestWhatItRefuses:
    async def test_a_bad_handle_is_refused_before_any_call(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="outlook_list_task_lists") as raised:
            _ = await _delete(client, task_list="Launch", confirm=_never_asked)

        assert _NOTHING_DELETED in str(raised.value)
        assert graph.calls.call_count == 0

    @pytest.mark.parametrize("well_known", ["defaultList", "flaggedEmails"])
    async def test_a_built_in_list_is_refused_before_any_question(
        self, client: GraphServiceClient, graph: respx.MockRouter, well_known: str
    ) -> None:
        _ = _read(graph, well_known=well_known)
        delete = _deleted(graph)

        with pytest.raises(ToolError, match="Microsoft To Do does not delete") as raised:
            _ = await _delete(client, confirm=_never_asked)

        assert _NOTHING_DELETED in str(raised.value)
        assert delete.call_count == 0


class TestThePersonBetweenTheReadAndTheDelete:
    async def test_a_private_list_is_still_asked_about(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _read(graph, is_shared=False)
        _ = _deleted(graph)

        assert await _question_for(client) == _ASKED

    async def test_a_shared_list_that_the_user_owns_says_others_lose_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _read(graph, is_shared=True, is_owner=True)
        _ = _deleted(graph)

        assert await _question_for(client) == (
            f"{_ASKED} Other people share this list. They lose it too."
        )

    async def test_a_list_that_another_person_shared_claims_nothing_undocumented(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _read(graph, is_shared=True, is_owner=False)
        _ = _deleted(graph)

        assert await _question_for(client) == (
            f"{_ASKED} Another person shared this list with you. Microsoft does not document "
            + "what this delete does for that person."
        )

    async def test_a_list_of_unknown_audience_says_others_can_lose_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _read(graph, is_shared=None)
        _ = _deleted(graph)

        assert await _question_for(client) == (
            f"{_ASKED} Microsoft 365 did not report this list as private. Other people can lose "
            + "it too."
        )

    async def test_a_person_who_declines_keeps_the_list(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _read(graph)
        delete = _deleted(graph)

        with pytest.raises(ToolError) as raised:
            _ = await _delete(client, confirm=_refuses)

        assert str(raised.value) == _NOTHING_DELETED
        assert delete.call_count == 0

    async def test_a_question_that_a_modern_client_must_answer_is_returned_before_any_delete(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _read(graph)
        delete = _deleted(graph)

        async def ask_back(question: str, about: str) -> InputRequiredResult:
            assert question
            assert about
            return InputRequiredResult(input_requests={}, request_state="state")

        answer = await delete_task_list(client, task_list=_URI, confirm=ask_back)

        assert isinstance(answer, InputRequiredResult)
        assert delete.call_count == 0


class TestWhatItAdvertises:
    async def test_it_is_a_destructive_idempotent_write_that_requires_a_list(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        deleter.register(mcp, transport)
        tool = cast("Tool", await mcp.get_tool(deleter.TOOL_NAME))

        assert tool.annotations is not None
        assert tool.annotations.model_dump(exclude_none=True, by_alias=True) == (
            WRITE_DESTRUCTIVE_IDEMPOTENT
        )
        assert cast("dict[str, object]", tool.parameters)["required"] == ["task_list"]
