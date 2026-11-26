from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import cast

import pytest
import respx
from fastmcp.exceptions import ToolError
from mcp.types import InputRequiredResult
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.shared.outlook.tasks import Status, TaskFields, TaskRepeat
from office_365_mcp.shared.seam import Confirm
from office_365_mcp.tools.outlook_add_task_link import add_task_link
from office_365_mcp.tools.outlook_add_task_step import add_task_step
from office_365_mcp.tools.outlook_create_task import create_task
from office_365_mcp.tools.outlook_delete_task import delete_task
from office_365_mcp.tools.outlook_delete_task_attachment import delete_task_attachment
from office_365_mcp.tools.outlook_delete_task_link import delete_task_link
from office_365_mcp.tools.outlook_delete_task_list import delete_task_list
from office_365_mcp.tools.outlook_delete_task_step import delete_task_step
from office_365_mcp.tools.outlook_rename_task_list import rename_task_list
from office_365_mcp.tools.outlook_set_task_status import set_task_status
from office_365_mcp.tools.outlook_update_task import TaskChange, update_task
from office_365_mcp.tools.outlook_update_task_step import update_task_step
from tests.tools.todo_graph import (
    ETAG,
    FILE_URI,
    LINK_URI,
    OTHER_FILE_URI,
    OTHER_LINK_URI,
    OTHER_STEP_URI,
    OTHER_TASK_LIST_URI,
    OTHER_TASK_URI,
    SEEN,
    STEP_URI,
    TASK_LIST_URI,
    TASK_URI,
    Entity,
    todo_graph,
    writes,
    written,
)

type Arguments = Mapping[str, object]

type Call = Callable[[GraphServiceClient, Arguments, Confirm, bool], Awaitable[object]]


def _text(arguments: Arguments, name: str) -> str:
    return cast("str", arguments[name])


def _rest(arguments: Arguments, handle: str) -> dict[str, object]:
    return {name: value for name, value in arguments.items() if name != handle}


async def _create(
    client: GraphServiceClient, arguments: Arguments, confirm: Confirm, pending: bool
) -> object:
    return await create_task(
        client,
        task_list=_text(arguments, "task_list"),
        fields=TaskFields.model_validate(_rest(arguments, "task_list")),
        confirm=confirm,
        answer_pending=pending,
    )


async def _update(
    client: GraphServiceClient, arguments: Arguments, confirm: Confirm, pending: bool
) -> object:
    return await update_task(
        client,
        uri=_text(arguments, "uri"),
        change=TaskChange.model_validate(_rest(arguments, "uri")),
        confirm=confirm,
        answer_pending=pending,
    )


async def _status(
    client: GraphServiceClient, arguments: Arguments, confirm: Confirm, pending: bool
) -> object:
    return await set_task_status(
        client,
        uri=_text(arguments, "uri"),
        status=cast("Status", arguments["status"]),
        time_zone=_text(arguments, "time_zone"),
        confirm=confirm,
        answer_pending=pending,
    )


async def _add_step(
    client: GraphServiceClient, arguments: Arguments, confirm: Confirm, pending: bool
) -> object:
    return await add_task_step(
        client,
        uri=_text(arguments, "uri"),
        text=_text(arguments, "text"),
        is_checked=cast("bool", arguments["is_checked"]),
        confirm=confirm,
        answer_pending=pending,
    )


async def _update_step(
    client: GraphServiceClient, arguments: Arguments, confirm: Confirm, pending: bool
) -> object:
    return await update_task_step(
        client,
        step=_text(arguments, "step"),
        text=cast("str | None", arguments.get("text")),
        is_checked=cast("bool | None", arguments.get("is_checked")),
        confirm=confirm,
        answer_pending=pending,
    )


async def _add_link(
    client: GraphServiceClient, arguments: Arguments, confirm: Confirm, pending: bool
) -> object:
    return await add_task_link(
        client,
        uri=_text(arguments, "uri"),
        web_url=_text(arguments, "web_url"),
        title=_text(arguments, "title"),
        application=_text(arguments, "application"),
        confirm=confirm,
        answer_pending=pending,
    )


async def _rename(
    client: GraphServiceClient, arguments: Arguments, confirm: Confirm, pending: bool
) -> object:
    return await rename_task_list(
        client,
        task_list=_text(arguments, "task_list"),
        name=_text(arguments, "name"),
        confirm=confirm,
        answer_pending=pending,
    )


async def _delete_task(
    client: GraphServiceClient, arguments: Arguments, confirm: Confirm, pending: bool
) -> object:
    return await delete_task(
        client, uri=_text(arguments, "uri"), confirm=confirm, answer_pending=pending
    )


async def _delete_list(
    client: GraphServiceClient, arguments: Arguments, confirm: Confirm, pending: bool
) -> object:
    return await delete_task_list(
        client, task_list=_text(arguments, "task_list"), confirm=confirm, answer_pending=pending
    )


async def _delete_step(
    client: GraphServiceClient, arguments: Arguments, confirm: Confirm, pending: bool
) -> object:
    return await delete_task_step(
        client, step=_text(arguments, "step"), confirm=confirm, answer_pending=pending
    )


async def _delete_link(
    client: GraphServiceClient, arguments: Arguments, confirm: Confirm, pending: bool
) -> object:
    return await delete_task_link(
        client, link=_text(arguments, "link"), confirm=confirm, answer_pending=pending
    )


async def _delete_file(
    client: GraphServiceClient, arguments: Arguments, confirm: Confirm, pending: bool
) -> object:
    return await delete_task_attachment(
        client, attachment=_text(arguments, "attachment"), confirm=confirm, answer_pending=pending
    )


@dataclass(frozen=True, slots=True)
class _Write:
    tool: str
    call: Call
    arguments: Arguments
    variants: Mapping[str, object]
    shows: tuple[Entity, ...]


_REMINDER = datetime(2026, 11, 27, 9, 0)

WRITES = (
    _Write(
        "outlook_create_task",
        _create,
        {"task_list": TASK_LIST_URI, "title": "Book the venue"},
        {
            "task_list": OTHER_TASK_LIST_URI,
            "title": "Book the hall",
            "notes_html": "<p>Twenty people.</p>",
            "due_date": date(2026, 11, 30),
            "priority": "high",
            "start_date": date(2026, 11, 23),
            "reminder_at": _REMINDER,
            "categories": ("Red category",),
            "time_zone": "Europe/Zurich",
        },
        ("list",),
    ),
    _Write(
        "outlook_update_task",
        _update,
        {"uri": TASK_URI, "title": "Book the venue"},
        {
            "uri": OTHER_TASK_URI,
            "title": "Book the hall",
            "notes_html": "<p>Twenty people.</p>",
            "due_date": date(2026, 11, 30),
            "clear_due_date": True,
            "priority": "high",
            "start_date": date(2026, 11, 23),
            "clear_start_date": True,
            "reminder_at": _REMINDER,
            "clear_reminder": True,
            "repeat": TaskRepeat(every="week"),
            "clear_repeat": True,
            "categories": (),
            "time_zone": "Europe/Zurich",
        },
        ("list", "task"),
    ),
    _Write(
        "outlook_set_task_status",
        _status,
        {"uri": TASK_URI, "status": "completed", "time_zone": "UTC"},
        {"uri": OTHER_TASK_URI, "status": "in_progress", "time_zone": "Europe/Zurich"},
        ("list", "task"),
    ),
    _Write(
        "outlook_add_task_step",
        _add_step,
        {"uri": TASK_URI, "text": "Call the hotel", "is_checked": False},
        {"uri": OTHER_TASK_URI, "text": "Call Anna", "is_checked": True},
        ("list", "task"),
    ),
    _Write(
        "outlook_update_task_step",
        _update_step,
        {"step": STEP_URI, "text": "Call Anna"},
        {"step": OTHER_STEP_URI, "text": "Call Tom", "is_checked": True},
        ("list", "task", "step"),
    ),
    _Write(
        "outlook_add_task_link",
        _add_link,
        {
            "uri": TASK_URI,
            "web_url": "https://example.invalid/q3",
            "title": "Q3 report",
            "application": "Outlook",
        },
        {
            "uri": OTHER_TASK_URI,
            "web_url": "https://example.invalid/q4",
            "title": "Q4 report",
            "application": "Teams",
        },
        ("list", "task"),
    ),
    _Write(
        "outlook_rename_task_list",
        _rename,
        {"task_list": TASK_LIST_URI, "name": "Q4 launch"},
        {"task_list": OTHER_TASK_LIST_URI, "name": "Q1 launch"},
        ("list",),
    ),
    _Write(
        "outlook_delete_task",
        _delete_task,
        {"uri": TASK_URI},
        {"uri": OTHER_TASK_URI},
        ("list", "task"),
    ),
    _Write(
        "outlook_delete_task_list",
        _delete_list,
        {"task_list": TASK_LIST_URI},
        {"task_list": OTHER_TASK_LIST_URI},
        ("list",),
    ),
    _Write(
        "outlook_delete_task_step",
        _delete_step,
        {"step": STEP_URI},
        {"step": OTHER_STEP_URI},
        ("list", "task", "step"),
    ),
    _Write(
        "outlook_delete_task_link",
        _delete_link,
        {"link": LINK_URI},
        {"link": OTHER_LINK_URI},
        ("list", "task", "link"),
    ),
    _Write(
        "outlook_delete_task_attachment",
        _delete_file,
        {"attachment": FILE_URI},
        {"attachment": OTHER_FILE_URI},
        ("list", "task", "file"),
    ),
)

_SHOWN_VALUES: Mapping[Entity, Mapping[str, Mapping[str, object]]] = {
    "list": {
        "list name": {"displayName": "Team offsite"},
        "list audience": {"isShared": None},
    },
    "task": {"task title": {"title": "Book the hall"}, "task etag": {"@odata.etag": 'W/"2"'}},
    "step": {"step words": {"displayName": "Call Anna"}, "step check": {"isChecked": True}},
    "link": {
        "link title": {"displayName": "Q4 report"},
        "link address": {"webUrl": "https://x.invalid"},
    },
    "file": {"file name": {"name": "Budget.xlsx"}},
}

_ETAG_GUARDED = frozenset({"outlook_set_task_status", "outlook_update_task", "outlook_delete_task"})


def _ids(write: _Write) -> str:
    return write.tool


async def _about(
    client: GraphServiceClient,
    graph: respx.MockRouter,
    write: _Write,
    arguments: Arguments,
    changed: Mapping[Entity, Mapping[str, object]],
) -> str:
    todo_graph(graph, changed=changed)
    asked: list[str] = []

    async def ask_back(_question: str, about: str) -> InputRequiredResult:
        asked.append(about)
        return InputRequiredResult(input_requests={}, request_state=about)

    answer = await write.call(client, arguments, ask_back, False)
    assert isinstance(answer, InputRequiredResult), f"{write.tool} did not ask"
    [about] = asked
    return about


async def _agrees(question: str, about: str) -> None:
    assert question
    assert about


class TestTheAnswerIsBoundToWhatTheQuestionShows:
    @pytest.mark.parametrize("write", WRITES, ids=_ids)
    async def test_a_changed_argument_or_a_changed_read_changes_the_digest(
        self, client: GraphServiceClient, graph: respx.MockRouter, write: _Write
    ) -> None:
        first = await _about(client, graph, write, write.arguments, {})
        again = await _about(client, graph, write, write.arguments, {})
        argument_digests = {
            name: await _about(client, graph, write, {**write.arguments, name: value}, {})
            for name, value in write.variants.items()
        }
        read_digests = {
            label: await _about(client, graph, write, write.arguments, {entity: change})
            for entity in write.shows
            for label, change in _SHOWN_VALUES[entity].items()
        }

        assert again == first
        assert set(write.variants) >= set(write.arguments)
        assert not [name for name, about in argument_digests.items() if about == first]
        assert not [label for label, about in read_digests.items() if about == first]
        assert not writes(graph)

    @pytest.mark.parametrize("write", WRITES, ids=_ids)
    async def test_the_older_protocol_refuses_when_the_reads_change_after_the_answer(
        self, client: GraphServiceClient, graph: respx.MockRouter, write: _Write
    ) -> None:
        todo_graph(graph)
        written(graph)

        async def agrees_while_the_list_is_renamed(_question: str, _about: str) -> None:
            todo_graph(graph, changed={"list": {"displayName": "Renamed meanwhile"}})

        with pytest.raises(ToolError, match="changed while the user decided") as raised:
            _ = await write.call(client, write.arguments, agrees_while_the_list_is_renamed, False)

        assert "Read the item again" in str(raised.value)
        assert not writes(graph)


class TestThePersonBeforeTheWrite:
    @pytest.mark.parametrize("write", WRITES, ids=_ids)
    async def test_a_person_who_declines_gets_nothing_written(
        self, client: GraphServiceClient, graph: respx.MockRouter, write: _Write
    ) -> None:
        todo_graph(graph)
        written(graph)

        async def declines(_question: str, _about: str) -> str:
            return "The person did not agree."

        with pytest.raises(ToolError, match="The person did not agree."):
            _ = await write.call(client, write.arguments, declines, False)

        assert not writes(graph)


class TestTheWriteAfterTheAnswer:
    @pytest.mark.parametrize("write", WRITES, ids=_ids)
    async def test_only_a_task_change_sends_the_etag_that_the_person_saw(
        self, client: GraphServiceClient, graph: respx.MockRouter, write: _Write
    ) -> None:
        todo_graph(graph)
        written(graph)

        _ = await write.call(client, write.arguments, _agrees, False)

        [sent] = writes(graph)
        expected = ETAG if write.tool in _ETAG_GUARDED else None
        assert sent.request.headers.get("if-match") == expected

    @pytest.mark.parametrize(
        "write", [write for write in WRITES if write.tool in _ETAG_GUARDED], ids=_ids
    )
    async def test_a_task_that_changed_before_the_write_is_refused_and_not_sent_again(
        self, client: GraphServiceClient, graph: respx.MockRouter, write: _Write
    ) -> None:
        todo_graph(graph)
        written(graph, status=412)

        with pytest.raises(ToolError, match="The item changed while the user decided"):
            _ = await write.call(client, write.arguments, _agrees, False)

        assert len(writes(graph)) == 1

    @pytest.mark.parametrize("write", WRITES, ids=_ids)
    async def test_a_resumed_answer_reads_once_and_writes_once(
        self, client: GraphServiceClient, graph: respx.MockRouter, write: _Write
    ) -> None:
        todo_graph(graph)
        written(graph)

        _ = await write.call(client, write.arguments, _agrees, True)

        assert len(graph.calls) == len(write.shows) + 1
        assert len(writes(graph)) == 1


def test_the_table_names_every_entity_that_a_question_can_show() -> None:
    assert {entity for write in WRITES for entity in write.shows} == set(SEEN)
