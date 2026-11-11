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
from office_365_mcp.tools import outlook_delete_category as deleter
from office_365_mcp.tools.outlook_delete_category import DeletedCategory, delete_category

_ID_Q4 = "11111111-aaaa-4aaa-8aaa-000000000001"

_ID_Q1 = "11111111-aaaa-4aaa-8aaa-000000000002"

_PATH = "/me/outlook/masterCategories"

_NOTHING_DELETED = "The category was not deleted."

_LIST = {
    "value": [
        {"id": _ID_Q1, "displayName": "Follow-up Q1"},
        {"id": _ID_Q4, "displayName": "Follow-up Q4"},
    ]
}


def _listed(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_PATH).mock(return_value=httpx.Response(200, json=_LIST))


def _deleted(graph: respx.MockRouter, status: int = 204) -> respx.Route:
    return graph.delete(f"{_PATH}/{_ID_Q4}").mock(return_value=httpx.Response(status))


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
    client: GraphServiceClient, *, name: str = "Follow-up Q4", confirm: Confirm = _agrees
) -> DeletedCategory:
    answer = await delete_category(client, name=name, confirm=confirm)
    assert isinstance(answer, DeletedCategory), "this call was answered with a question"
    return answer


class TestWhatItSendsToGraph:
    async def test_it_lists_the_categories_and_deletes_the_one_with_that_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _listed(graph)
        _ = _deleted(graph)

        answer = await _delete(client)

        made = cast("Sequence[Call]", graph.calls)
        assert [(call.request.method, call.request.url.path) for call in made] == [
            ("GET", f"/v1.0{_PATH}"),
            ("DELETE", f"/v1.0{_PATH}/{_ID_Q4}"),
        ]
        assert made[0].request.url.params["$select"] == "id,displayName"
        assert (answer.name, answer.deleted) == ("Follow-up Q4", True)

    async def test_the_name_matches_without_regard_to_letter_case(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _listed(graph)
        delete = _deleted(graph)

        answer = await _delete(client, name="FOLLOW-UP q4")

        assert delete.call_count == 1
        assert answer.name == "Follow-up Q4"

    async def test_a_category_that_is_gone_after_the_read_is_reported_as_deleted(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _listed(graph)
        _ = _deleted(graph, status=404)

        answer = await _delete(client)

        assert answer.deleted is True


class TestWhatItRefuses:
    async def test_a_name_that_is_not_in_the_list_deletes_nothing_and_asks_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _listed(graph)
        delete = _deleted(graph)

        with pytest.raises(ToolError, match="outlook_list_categories") as raised:
            _ = await _delete(client, name="Follow-up Q2", confirm=_never_asked)

        assert "nothing was deleted" in str(raised.value)
        assert delete.call_count == 0


class TestThePersonBetweenTheReadAndTheDelete:
    async def test_the_question_names_the_category_and_is_bound_to_its_id(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _listed(graph)
        _ = _deleted(graph)
        asked: list[tuple[str, str]] = []

        async def capture(question: str, about: str) -> str | None:
            asked.append((question, about))
            return None

        _ = await _delete(client, confirm=capture)

        [(question, about)] = asked
        assert "'Follow-up Q4'" in question
        assert about

    async def test_a_person_who_declines_keeps_the_category(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _listed(graph)
        delete = _deleted(graph)

        with pytest.raises(ToolError) as raised:
            _ = await _delete(client, confirm=_refuses)

        assert str(raised.value) == _NOTHING_DELETED
        assert delete.call_count == 0

    async def test_a_question_that_a_modern_client_must_answer_is_returned_before_any_delete(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _listed(graph)
        delete = _deleted(graph)

        async def ask_back(question: str, about: str) -> InputRequiredResult:
            assert question
            assert about
            return InputRequiredResult(input_requests={}, request_state="state")

        answer = await delete_category(client, name="Follow-up Q4", confirm=ask_back)

        assert isinstance(answer, InputRequiredResult)
        assert delete.call_count == 0


class TestWhatItAdvertises:
    async def test_it_is_a_destructive_idempotent_write_that_requires_a_name(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        deleter.register(mcp, transport)
        tool = cast("Tool", await mcp.get_tool(deleter.TOOL_NAME))

        assert tool.annotations is not None
        assert tool.annotations.model_dump(exclude_none=True, by_alias=True) == (
            WRITE_DESTRUCTIVE_IDEMPOTENT
        )
        assert cast("dict[str, object]", tool.parameters)["required"] == ["name"]
