import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import ModuleType
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel

from office_365_mcp.graph_client import GraphFailure
from office_365_mcp.shared.seam import WRITE_DESTRUCTIVE_IDEMPOTENT, Confirm
from office_365_mcp.tools import (
    outlook_delete_task,
    outlook_delete_task_attachment,
    outlook_delete_task_link,
    outlook_delete_task_list,
    outlook_delete_task_step,
)
from tests.tools.todo_graph import (
    FILE_URI,
    LINK_URI,
    PATHS,
    STEP_URI,
    TASK_LIST_URI,
    TASK_URI,
    Entity,
    reads,
    todo_graph,
    writes,
    written,
)

type Delete = Callable[[GraphServiceClient, str, Confirm, bool], Awaitable[object]]


async def _task(client: GraphServiceClient, uri: str, confirm: Confirm, pending: bool) -> object:
    return await outlook_delete_task.delete_task(
        client, uri=uri, confirm=confirm, answer_pending=pending
    )


async def _list(client: GraphServiceClient, uri: str, confirm: Confirm, pending: bool) -> object:
    return await outlook_delete_task_list.delete_task_list(
        client, task_list=uri, confirm=confirm, answer_pending=pending
    )


async def _step(client: GraphServiceClient, uri: str, confirm: Confirm, pending: bool) -> object:
    return await outlook_delete_task_step.delete_task_step(
        client, step=uri, confirm=confirm, answer_pending=pending
    )


async def _link(client: GraphServiceClient, uri: str, confirm: Confirm, pending: bool) -> object:
    return await outlook_delete_task_link.delete_task_link(
        client, link=uri, confirm=confirm, answer_pending=pending
    )


async def _file(client: GraphServiceClient, uri: str, confirm: Confirm, pending: bool) -> object:
    return await outlook_delete_task_attachment.delete_task_attachment(
        client, attachment=uri, confirm=confirm, answer_pending=pending
    )


@dataclass(frozen=True, slots=True)
class _Delete:
    module: ModuleType
    call: Delete
    uri: str
    argument: str
    reads: tuple[Entity, ...]
    name_field: str
    name: str
    declined: str
    asked: str

    @property
    def tool(self) -> str:
        return cast("str", self.module.TOOL_NAME)

    async def __call__(
        self, client: GraphServiceClient, confirm: Confirm, *, pending: bool, uri: str = ""
    ) -> object:
        return await self.call(client, uri or self.uri, confirm, pending)


_DELETED_ID: Mapping[Entity, str] = {
    "list": "/AAMkSYNTHETIC-list-0001",
    "task": "/tasks/AAMkSYNTHETIC-task-0001",
    "step": "/checklistItems/SYNTHETIC-step-0001",
    "link": "/linkedResources/SYNTHETIC-link-0001",
    "file": "/attachments/SYNTHETIC-file-0001",
}

_IN_THE_LIST = "from the task 'Book the venue' in the list 'Team launch'?"

DELETES = (
    _Delete(
        outlook_delete_task,
        _task,
        TASK_URI,
        "uri",
        ("list", "task"),
        "title",
        "Book the venue",
        "The task was not deleted.",
        "Delete the task 'Book the venue' from the list 'Team launch'?",
    ),
    _Delete(
        outlook_delete_task_list,
        _list,
        TASK_LIST_URI,
        "task_list",
        ("list",),
        "name",
        "Team launch",
        "Nothing was deleted.",
        "Delete the list 'Team launch' and every task in it?",
    ),
    _Delete(
        outlook_delete_task_step,
        _step,
        STEP_URI,
        "step",
        ("list", "task", "step"),
        "text",
        "Call the hotel",
        "The step was not deleted.",
        f"Delete the step 'Call the hotel' {_IN_THE_LIST}",
    ),
    _Delete(
        outlook_delete_task_link,
        _link,
        LINK_URI,
        "link",
        ("list", "task", "link"),
        "title",
        "Q3 report",
        "The link was not deleted.",
        "Delete the link 'Q3 report', which opens 'https://example.invalid/q3', "
        + f"{_IN_THE_LIST}",
    ),
    _Delete(
        outlook_delete_task_attachment,
        _file,
        FILE_URI,
        "attachment",
        ("list", "task", "file"),
        "name",
        "Agenda.pdf",
        "The file was not deleted.",
        f"Delete the file 'Agenda.pdf' {_IN_THE_LIST}",
    ),
)

_GONE = [
    pytest.param(delete, gone, id=f"{delete.tool}-{gone or 'delete'}")
    for delete in DELETES
    for gone in (*delete.reads, None)
]

_NOT_A_HANDLE = [
    pytest.param(delete, wrong, id=f"{delete.tool}-{index}")
    for delete in DELETES
    for index, wrong in enumerate(
        (
            "Book the venue",
            *(uri for uri in (TASK_LIST_URI, TASK_URI, STEP_URI, LINK_URI, FILE_URI)),
        )
    )
    if wrong != delete.uri
]

_SHARING: Mapping[str, tuple[bool | None, str]] = {
    "private": (False, ""),
    "shared": (True, " Other people share this list, so they can lose"),
    "unknown": (
        None,
        " Microsoft 365 did not report this list as private, so other people can lose",
    ),
}


def _ids(delete: _Delete) -> str:
    return delete.tool


def _entity_at(path: str) -> Entity:
    return next(entity for entity, pattern in PATHS.items() if re.search(pattern, path))


async def _agrees(question: str, about: str) -> None:
    assert question
    assert about


async def _never_asked(question: str, _about: str) -> None:
    raise AssertionError(f"a refused delete was put to a person: {question!r}")


def _named(answer: object, delete: _Delete) -> tuple[object, object]:
    assert isinstance(answer, BaseModel), f"{delete.tool} answered with {answer!r}"
    dumped = answer.model_dump()
    return dumped[delete.name_field], dumped["outcome"]


async def _question(client: GraphServiceClient, delete: _Delete) -> str:
    asked: list[str] = []

    async def remember(question: str, _about: str) -> str:
        asked.append(question)
        return delete.declined

    with pytest.raises(ToolError):
        _ = await delete(client, remember, pending=False)
    [question] = asked
    return question


class TestWhatADeleteSendsToGraph:
    @pytest.mark.parametrize("delete", DELETES, ids=_ids)
    async def test_it_reads_the_list_then_the_task_then_the_part_and_deletes_once(
        self, client: GraphServiceClient, graph: respx.MockRouter, delete: _Delete
    ) -> None:
        todo_graph(graph)
        written(graph)

        answer = await delete(client, _agrees, pending=True)

        assert [_entity_at(path) for path in reads(graph)] == list(delete.reads)
        [sent] = writes(graph)
        target = sent.request.url.path.removeprefix("/v1.0")
        assert sent.request.method == "DELETE"
        assert re.search(PATHS[delete.reads[-1]], target) is not None
        assert target.endswith(_DELETED_ID[delete.reads[-1]])
        assert _named(answer, delete) == (delete.name, "deleted")

    @pytest.mark.parametrize(("delete", "gone"), _GONE)
    async def test_a_404_at_any_read_or_at_the_delete_answers_not_found(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        delete: _Delete,
        gone: Entity | None,
    ) -> None:
        todo_graph(graph, missing=gone)
        written(graph, status=200 if gone else 404)

        answer = await delete(client, _agrees, pending=True)

        assert _named(answer, delete) == (None if gone else delete.name, "not_found")
        assert len(writes(graph)) == (0 if gone else 1)

    @pytest.mark.parametrize("delete", DELETES, ids=_ids)
    async def test_a_delete_that_graph_fails_is_sent_once(
        self, client: GraphServiceClient, graph: respx.MockRouter, delete: _Delete
    ) -> None:
        todo_graph(graph)
        written(graph, status=503)

        with pytest.raises(GraphFailure):
            _ = await delete(client, _agrees, pending=True)

        assert len(writes(graph)) == 1


class TestWhatADeleteRefuses:
    @pytest.mark.parametrize(("delete", "wrong"), _NOT_A_HANDLE)
    async def test_a_handle_of_another_kind_is_refused_before_any_call(
        self, client: GraphServiceClient, graph: respx.MockRouter, delete: _Delete, wrong: str
    ) -> None:
        with pytest.raises(ToolError, match=f"`{delete.argument}`") as raised:
            _ = await delete(client, _never_asked, pending=False, uri=wrong)

        assert delete.declined in str(raised.value)
        assert not graph.calls

    @pytest.mark.parametrize("well_known", ["defaultList", "flaggedEmails"])
    async def test_a_built_in_list_is_refused_before_any_question(
        self, client: GraphServiceClient, graph: respx.MockRouter, well_known: str
    ) -> None:
        todo_graph(graph, changed={"list": {"wellknownListName": well_known}})
        written(graph)
        delete = DELETES[1]

        with pytest.raises(ToolError, match="Microsoft To Do does not delete") as raised:
            _ = await delete(client, _never_asked, pending=False)

        assert delete.declined in str(raised.value)
        assert not writes(graph)


class TestThePersonBeforeTheDelete:
    @pytest.mark.parametrize("delete", DELETES, ids=_ids)
    @pytest.mark.parametrize("sharing", _SHARING)
    async def test_the_question_names_what_goes_and_who_else_can_lose_it(
        self, client: GraphServiceClient, graph: respx.MockRouter, delete: _Delete, sharing: str
    ) -> None:
        is_shared, note = _SHARING[sharing]
        todo_graph(graph, changed={"list": {"isShared": is_shared}})

        question = await _question(client, delete)

        assert question.startswith(f"{delete.asked}{note}")
        assert question.endswith("This connector cannot undo the delete.")

    @pytest.mark.parametrize("delete", DELETES[2:], ids=_ids)
    async def test_the_question_names_a_task_with_no_title(
        self, client: GraphServiceClient, graph: respx.MockRouter, delete: _Delete
    ) -> None:
        todo_graph(graph, changed={"task": {"title": None}})

        question = await _question(client, delete)

        assert "from a task with no title in the list 'Team launch'?" in question


class TestWhatADeleteAdvertises:
    @pytest.mark.parametrize("delete", DELETES, ids=_ids)
    async def test_it_is_a_destructive_idempotent_write_that_requires_one_handle(
        self, transport: httpx.AsyncClient, delete: _Delete
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        cast("Callable[[FastMCP, httpx.AsyncClient], None]", delete.module.register)(mcp, transport)
        tool = cast("Tool", await mcp.get_tool(delete.tool))

        assert tool.annotations is not None
        assert tool.annotations.model_dump(exclude_none=True, by_alias=True) == (
            WRITE_DESTRUCTIVE_IDEMPOTENT
        )
        assert cast("dict[str, object]", tool.parameters)["required"] == [delete.argument]
