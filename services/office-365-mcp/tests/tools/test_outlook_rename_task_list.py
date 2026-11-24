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

from office_365_mcp.shared.outlook.tasks import TaskListSummary
from office_365_mcp.shared.seam import WRITE_DESTRUCTIVE_IDEMPOTENT, Confirm
from office_365_mcp.tools import outlook_rename_task_list as renamer
from office_365_mcp.tools.outlook_rename_task_list import rename_task_list

_LIST_ID = "list-0001"

_URI = f"outlook:///tasklists/{_LIST_ID}"

_PATH = f"/me/todo/lists/{_LIST_ID}"

_NOTHING_CHANGED = "Nothing was changed."


def _list(
    *, is_shared: bool | None = False, well_known: str = "none", name: str = "Launch"
) -> dict[str, object]:
    return {
        "id": _LIST_ID,
        "displayName": name,
        "isShared": is_shared,
        "isOwner": True,
        "wellknownListName": well_known,
    }


def _read(
    graph: respx.MockRouter, *, is_shared: bool | None = False, well_known: str = "none"
) -> respx.Route:
    payload = _list(is_shared=is_shared, well_known=well_known)
    return graph.get(_PATH).mock(return_value=httpx.Response(200, json=payload))


def _patched(graph: respx.MockRouter) -> respx.Route:
    renamed = {**_list(), "displayName": "Q4 launch"}
    return graph.patch(_PATH).mock(return_value=httpx.Response(200, json=renamed))


async def _refuses(question: str, about: str) -> str | None:
    assert question
    assert about
    return _NOTHING_CHANGED


async def _never_asked(question: str, about: str) -> str | None:
    raise AssertionError(f"this rename was put to a person: {question!r} ({about})")


async def _rename(
    client: GraphServiceClient,
    *,
    task_list: str = _URI,
    name: str = "Q4 launch",
    confirm: Confirm = _never_asked,
) -> TaskListSummary:
    answer = await rename_task_list(client, task_list=task_list, name=name, confirm=confirm)
    assert isinstance(answer, TaskListSummary), "this call was answered with a question"
    return answer


class TestWhatItSendsToGraph:
    async def test_it_reads_the_list_and_patches_only_the_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _read(graph)
        _ = _patched(graph)

        answer = await _rename(client)

        made = cast("Sequence[Call]", graph.calls)
        assert [(call.request.method, call.request.url.path) for call in made] == [
            ("GET", f"/v1.0{_PATH}"),
            ("PATCH", f"/v1.0{_PATH}"),
        ]
        assert "$select" not in made[0].request.url.params
        assert json.loads(made[1].request.content) == {"displayName": "Q4 launch"}
        assert (answer.uri, answer.name) == (_URI, "Q4 launch")


class TestWhatItRefuses:
    async def test_a_bad_handle_is_refused_before_any_call(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="outlook_list_task_lists") as raised:
            _ = await _rename(client, task_list="Launch")

        assert _NOTHING_CHANGED in str(raised.value)
        assert graph.calls.call_count == 0

    @pytest.mark.parametrize("well_known", ["defaultList", "flaggedEmails"])
    async def test_a_built_in_list_is_refused_before_any_write_or_question(
        self, client: GraphServiceClient, graph: respx.MockRouter, well_known: str
    ) -> None:
        _ = _read(graph, well_known=well_known, is_shared=True)
        patch = _patched(graph)

        with pytest.raises(ToolError, match="Microsoft To Do does not rename") as raised:
            _ = await _rename(client)

        assert _NOTHING_CHANGED in str(raised.value)
        assert patch.call_count == 0


class TestThePersonBeforeTheRename:
    async def test_a_private_list_is_renamed_without_a_question(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _read(graph, is_shared=False)
        patch = _patched(graph)

        _ = await _rename(client, confirm=_never_asked)

        assert patch.call_count == 1

    async def test_a_shared_list_asks_with_both_names(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _read(graph, is_shared=True)
        _ = _patched(graph)
        asked: list[tuple[str, str]] = []

        async def capture(question: str, about: str) -> str | None:
            asked.append((question, about))
            return None

        _ = await _rename(client, confirm=capture)

        [(question, about)] = asked
        assert question == (
            "Rename the list 'Launch' to 'Q4 launch'? Other people share this list. They see "
            + "the new name."
        )
        assert about

    async def test_a_list_of_unknown_audience_asks_too(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _read(graph, is_shared=None)
        _ = _patched(graph)
        asked: list[str] = []

        async def capture(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _rename(client, confirm=capture)

        [question] = asked
        assert "did not report this list as private" in question

    async def test_a_person_who_declines_keeps_the_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _read(graph, is_shared=True)
        patch = _patched(graph)

        with pytest.raises(ToolError) as raised:
            _ = await _rename(client, confirm=_refuses)

        assert str(raised.value) == _NOTHING_CHANGED
        assert patch.call_count == 0

    async def test_a_question_that_a_modern_client_must_answer_is_returned_before_any_write(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _read(graph, is_shared=True)
        patch = _patched(graph)

        async def ask_back(question: str, about: str) -> InputRequiredResult:
            assert question
            assert about
            return InputRequiredResult(input_requests={}, request_state="state")

        answer = await rename_task_list(client, task_list=_URI, name="Q4 launch", confirm=ask_back)

        assert isinstance(answer, InputRequiredResult)
        assert patch.call_count == 0


class TestWhatItAdvertises:
    async def test_it_is_a_destructive_idempotent_write_that_requires_a_list_and_a_name(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        renamer.register(mcp, transport)
        tool = cast("Tool", await mcp.get_tool(renamer.TOOL_NAME))

        assert tool.annotations is not None
        assert tool.annotations.model_dump(exclude_none=True, by_alias=True) == (
            WRITE_DESTRUCTIVE_IDEMPOTENT
        )
        assert cast("dict[str, object]", tool.parameters)["required"] == ["task_list", "name"]
