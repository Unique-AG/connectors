import functools
import json
from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import cast, override

import httpx
import pytest
import respx
from fastmcp import Client, FastMCP
from fastmcp.client.elicitation import ElicitRequestParams, ElicitResult
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError

from tests.e2e.test_scenarios import build_server, patch_obo
from tests.tools.scenarios.support import Person, call

LIST_ID = "AAMkSYNTHETIClist0001"
TASK_ID = "AAMkSYNTHETICtask0001"
TASK_LIST = f"outlook:///tasklists/{LIST_ID}"
TASK = f"outlook:///tasks/{LIST_ID}/{TASK_ID}"
LISTS = "/me/todo/lists"
TASKS = f"/me/todo/lists/{LIST_ID}/tasks"
ONE_TASK = f"{TASKS}/{TASK_ID}"
ONE_LIST = f"/me/todo/lists/{LIST_ID}"
ZURICH = "Europe/Zurich"
_EARLY_MIDNIGHT = "2026-11-23T00:00:00+14:00"


def _task(
    task_id: str,
    title: str,
    *,
    status: str = "notStarted",
    due_utc: str | None = None,
    **extra: object,
) -> dict[str, object]:
    task: dict[str, object] = {
        "id": task_id,
        "title": title,
        "status": status,
        "importance": "normal",
        "categories": [],
        "createdDateTime": "2026-11-02T08:00:00Z",
        "lastModifiedDateTime": "2026-11-02T08:00:00Z",
    }
    if due_utc is not None:
        task["dueDateTime"] = {"dateTime": due_utc, "timeZone": "UTC"}
    return task | extra


_SOME_TASK = _task(TASK_ID, "Book the venue")


def _list_is(graph: respx.MockRouter, *, shared: bool | None, name: str = "Tasks") -> None:
    listed: dict[str, object] = {"id": LIST_ID, "displayName": name}
    if shared is not None:
        listed["isShared"] = shared
    _ = graph.get(ONE_LIST).mock(return_value=httpx.Response(200, json=listed))


@dataclass
class _PersonWatchingWrites(Person):
    write: respx.Route | None = None
    writes_before_each_question: list[int] = field(default_factory=list)

    @override
    async def __call__(
        self, message: str, _type: type | None, params: ElicitRequestParams, _context: object
    ) -> ElicitResult[dict[str, str]]:
        assert self.write is not None, "the write route is set before the call"
        self.writes_before_each_question.append(self.write.call_count)
        return await super().__call__(message, _type, params, _context)


def _rows(answer: Mapping[str, object], key: str) -> Sequence[Mapping[str, object]]:
    return cast("Sequence[Mapping[str, object]]", answer[key])


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


class TestFindingTasks:
    async def test_the_lists_show_which_is_built_in_and_which_is_shared(
        self, graph: respx.MockRouter
    ) -> None:
        lists = [
            {"id": "L1", "displayName": "Tasks", "wellknownListName": "defaultList"},
            {"id": "L2", "displayName": "Flagged email", "wellknownListName": "flaggedEmails"},
            {
                "id": "L3",
                "displayName": "Team launch",
                "wellknownListName": "none",
                "isShared": True,
                "isOwner": False,
            },
        ]
        _ = graph.get(LISTS).mock(return_value=httpx.Response(200, json={"value": lists}))

        answer = await call("outlook_list_task_lists")

        assert [
            (row["name"], row["kind"], row["is_shared"]) for row in _rows(answer, "task_lists")
        ] == [
            ("Tasks", "tasks", None),
            ("Flagged email", "flagged_email", None),
            ("Team launch", None, True),
        ]
        assert _rows(answer, "task_lists")[2]["uri"] == "outlook:///tasklists/L3"

    async def test_open_tasks_due_this_week_are_listed_by_the_day_of_the_user(
        self, graph: respx.MockRouter
    ) -> None:
        tasks = [
            _task("T1", "Send the Q3 report", due_utc="2026-11-26T23:00:00.0000000"),
            _task("T2", "Book the venue", due_utc="2026-11-30T23:00:00.0000000"),
            _task("T4", "No date"),
        ]
        route = graph.get(TASKS).mock(return_value=httpx.Response(200, json={"value": tasks}))

        answer = await call(
            "outlook_list_tasks",
            task_list=TASK_LIST,
            due_after="2026-11-23",
            due_before="2026-11-29",
            time_zone=ZURICH,
        )

        [row] = _rows(answer, "tasks")
        assert (row["title"], row["due_date"], row["uri"]) == (
            "Send the Q3 report",
            "2026-11-27",
            f"outlook:///tasks/{LIST_ID}/T1",
        )
        assert answer["capped"] is False
        assert route.calls.last.request.url.params["$filter"] == "status ne 'completed'"

    async def test_a_task_due_on_a_day_matches_a_moment_later_that_day(
        self, graph: respx.MockRouter
    ) -> None:
        tasks = [
            _task("T1", "Send the Q3 report", due_utc="2026-11-22T23:00:00.0000000"),
            _task("T2", "Book the venue", due_utc="2026-11-21T23:00:00.0000000"),
        ]
        _ = graph.get(TASKS).mock(return_value=httpx.Response(200, json={"value": tasks}))

        answer = await call(
            "outlook_list_tasks",
            task_list=TASK_LIST,
            due_after="2026-11-23T12:00:00+01:00",
            time_zone=ZURICH,
        )

        assert [(row["title"], row["due_date"]) for row in _rows(answer, "tasks")] == [
            ("Send the Q3 report", "2026-11-23")
        ]

    @pytest.mark.parametrize(
        ("bound", "titles"),
        [
            ("due_before", ["Book the venue"]),
            ("due_after", ["Send the Q3 report", "Book the venue"]),
        ],
    )
    async def test_a_midnight_moment_with_an_offset_keeps_its_instant(
        self, graph: respx.MockRouter, bound: str, titles: list[str]
    ) -> None:
        tasks = [
            _task("T1", "Send the Q3 report", due_utc="2026-11-22T23:00:00.0000000"),
            _task("T2", "Book the venue", due_utc="2026-11-21T23:00:00.0000000"),
        ]
        _ = graph.get(TASKS).mock(return_value=httpx.Response(200, json={"value": tasks}))

        answer = await call(
            "outlook_list_tasks",
            task_list=TASK_LIST,
            show="any",
            time_zone=ZURICH,
            due_after=_EARLY_MIDNIGHT if bound == "due_after" else None,
            due_before=_EARLY_MIDNIGHT if bound == "due_before" else None,
        )

        assert [row["title"] for row in _rows(answer, "tasks")] == titles

    async def test_completed_tasks_are_listed_by_a_word_of_their_title(
        self, graph: respx.MockRouter
    ) -> None:
        tasks = [
            _task("T2", "Old REPORT", status="completed"),
            _task("T3", "Book the venue", status="completed"),
        ]
        route = graph.get(TASKS).mock(return_value=httpx.Response(200, json={"value": tasks}))

        answer = await call(
            "outlook_list_tasks", task_list=TASK_LIST, show="completed", title_contains="report"
        )

        assert [row["title"] for row in _rows(answer, "tasks")] == ["Old REPORT"]
        assert route.calls.last.request.url.params["$filter"] == "status eq 'completed'"

    @pytest.mark.parametrize(
        ("show", "sent"),
        [
            ("open", "status ne 'completed'"),
            ("completed", "status eq 'completed'"),
            ("any", None),
        ],
    )
    async def test_the_status_to_show_is_asked_of_microsoft_365(
        self, graph: respx.MockRouter, show: str, sent: str | None
    ) -> None:
        route = graph.get(TASKS).mock(return_value=httpx.Response(200, json={"value": []}))

        _ = await call("outlook_list_tasks", task_list=TASK_LIST, show=show)

        assert route.calls.last.request.url.params.get("$filter") == sent

    async def test_a_task_is_read_with_its_notes(self, graph: respx.MockRouter) -> None:
        task = _task(
            TASK_ID,
            "Send the Q3 report",
            due_utc="2026-11-26T23:00:00.0000000",
            importance="high",
            body={"contentType": "text", "content": "Use the numbers from Anna."},
        )
        _ = graph.get(ONE_TASK).mock(return_value=httpx.Response(200, json=task))

        answer = await call("outlook_read_task", uri=TASK, time_zone=ZURICH)

        assert (
            answer["notes"],
            answer["notes_format"],
            answer["priority"],
            answer["due_date"],
        ) == (
            "Use the numbers from Anna.",
            "text",
            "high",
            "2026-11-27",
        )


class TestChangingTasks:
    async def test_a_task_is_created_due_at_midnight_of_the_user_and_nobody_is_asked(
        self, graph: respx.MockRouter
    ) -> None:
        created = _task(TASK_ID, "Send the Q3 report", due_utc="2026-11-26T23:00:00.0000000")
        _list_is(graph, shared=False)
        route = graph.post(TASKS).mock(return_value=httpx.Response(201, json=created))
        person = Person()

        answer = await call(
            "outlook_create_task",
            task_list=TASK_LIST,
            title="Send the Q3 report",
            notes="Use the **numbers** from Anna.",
            due_date="2026-11-27",
            priority="high",
            time_zone=ZURICH,
            person=person,
        )

        assert _sent(route) == {
            "title": "Send the Q3 report",
            "body": {
                "content": "<p>Use the <strong>numbers</strong> from Anna.</p>",
                "contentType": "html",
            },
            "dueDateTime": {"dateTime": "2026-11-26T23:00:00", "timeZone": "UTC"},
            "importance": "high",
        }
        assert (answer["uri"], answer["due_date"], person.asked) == (TASK, "2026-11-27", [])
        assert route.call_count == 1

    async def test_a_task_is_completed(self, graph: respx.MockRouter) -> None:
        done = _task(TASK_ID, "Send the Q3 report", status="completed")
        _list_is(graph, shared=False)
        route = graph.patch(ONE_TASK).mock(return_value=httpx.Response(200, json=done))
        person = Person()

        answer = await call("outlook_complete_task", uri=TASK, person=person)

        assert _sent(route) == {"status": "completed"}
        assert (answer["status"], person.asked) == ("completed", [])

    async def test_a_task_is_reopened_and_its_due_date_is_removed(
        self, graph: respx.MockRouter
    ) -> None:
        reopened = _task(TASK_ID, "Send the Q3 report")
        _list_is(graph, shared=False)
        route = graph.patch(ONE_TASK).mock(return_value=httpx.Response(200, json=reopened))

        person = Person()

        answer = await call(
            "outlook_update_task",
            uri=TASK,
            status="not_started",
            clear_due_date=True,
            person=person,
        )

        assert _sent(route) == {"status": "notStarted", "dueDateTime": None}
        assert (answer["status"], answer["due_date"], person.asked) == ("not_started", None, [])


class TestASharedList:
    async def test_a_task_goes_into_a_shared_list_only_after_the_person_agrees(
        self, graph: respx.MockRouter
    ) -> None:
        _list_is(graph, shared=True, name="Team launch")
        created = _task(TASK_ID, "Book the venue")
        route = graph.post(TASKS).mock(return_value=httpx.Response(201, json=created))
        person = _PersonWatchingWrites(write=route)

        _ = await call(
            "outlook_create_task", task_list=TASK_LIST, title="Book the venue", person=person
        )

        [question] = person.asked
        assert "'Book the venue'" in question and "'Team launch'" in question
        assert person.writes_before_each_question == [0]
        assert route.call_count == 1

    async def test_a_declined_completion_in_a_shared_list_changes_nothing(
        self, graph: respx.MockRouter
    ) -> None:
        _list_is(graph, shared=True, name="Team launch")
        route = graph.patch(ONE_TASK).mock(return_value=httpx.Response(200, json=_SOME_TASK))

        with pytest.raises(ToolError, match="Nothing was changed"):
            _ = await call("outlook_complete_task", uri=TASK, person=Person(approval="no"))

        assert route.call_count == 0

    async def test_a_change_in_a_shared_list_is_asked_in_the_newer_protocol_too(
        self, graph: respx.MockRouter
    ) -> None:
        _list_is(graph, shared=True, name="Team launch")
        changed = _task(TASK_ID, "Book the venue", importance="high")
        route = graph.patch(ONE_TASK).mock(return_value=httpx.Response(200, json=changed))
        person = _PersonWatchingWrites(write=route)

        async with _modern_client(person) as client:
            answer = await client.call_tool(
                "outlook_update_task", {"uri": TASK, "priority": "high"}
            )

        assert answer.structured_content is not None
        [question] = person.asked
        assert "'Team launch'" in question
        assert person.writes_before_each_question == [0]
        assert route.call_count == 1

    async def test_a_list_that_does_not_say_whether_it_is_shared_is_asked_about(
        self, graph: respx.MockRouter
    ) -> None:
        _list_is(graph, shared=None, name="Team launch")
        route = graph.patch(ONE_TASK).mock(return_value=httpx.Response(200, json=_SOME_TASK))
        person = Person()

        _ = await call("outlook_complete_task", uri=TASK, person=person)

        [question] = person.asked
        assert "did not report as private" in question
        assert route.call_count == 1


class TestRefusals:
    async def test_a_list_name_is_refused_before_any_call(self, graph: respx.MockRouter) -> None:
        with pytest.raises(ToolError, match="No task was created"):
            _ = await call("outlook_create_task", task_list="Tasks", title="Anything")

        assert graph.calls.call_count == 0

    async def test_an_update_that_changes_nothing_is_refused(self, graph: respx.MockRouter) -> None:
        with pytest.raises(ToolError, match="nothing to change"):
            _ = await call("outlook_update_task", uri=TASK)

        assert graph.calls.call_count == 0

    async def test_a_due_date_and_its_removal_together_are_refused(
        self, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="not both"):
            _ = await call(
                "outlook_update_task", uri=TASK, due_date="2026-11-27", clear_due_date=True
            )

        assert graph.calls.call_count == 0

    async def test_a_windows_zone_name_is_refused(self, graph: respx.MockRouter) -> None:
        with pytest.raises(ToolError, match="IANA"):
            _ = await call(
                "outlook_list_tasks", task_list=TASK_LIST, time_zone="W. Europe Standard Time"
            )

        assert graph.calls.call_count == 0

    async def test_a_deleted_task_sends_the_assistant_back_to_the_list(
        self, graph: respx.MockRouter
    ) -> None:
        missing = {"error": {"code": "ErrorItemNotFound", "message": "The object was not found."}}
        _list_is(graph, shared=False)
        _ = graph.patch(ONE_TASK).mock(return_value=httpx.Response(404, json=missing))

        with pytest.raises(ToolError, match="find it again with outlook_list_tasks"):
            _ = await call("outlook_complete_task", uri=TASK)

    async def test_a_task_in_a_list_that_is_gone_sends_the_assistant_back_to_the_lists(
        self, graph: respx.MockRouter
    ) -> None:
        missing = {"error": {"code": "ErrorItemNotFound", "message": "The object was not found."}}
        _ = graph.get(ONE_LIST).mock(return_value=httpx.Response(404, json=missing))
        route = graph.patch(ONE_TASK).mock(return_value=httpx.Response(200, json=_SOME_TASK))

        with pytest.raises(ToolError, match="call outlook_list_task_lists again instead"):
            _ = await call("outlook_update_task", uri=TASK, priority="high")

        assert route.call_count == 0

    async def test_a_list_handle_is_refused_where_a_task_belongs(
        self, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="not task handles"):
            _ = await call("outlook_read_task", uri=TASK_LIST)

        assert graph.calls.call_count == 0

    async def test_a_deleted_list_sends_the_assistant_back_to_the_lists(
        self, graph: respx.MockRouter
    ) -> None:
        missing = {"error": {"code": "ErrorItemNotFound", "message": "The object was not found."}}
        _ = graph.get(TASKS).mock(return_value=httpx.Response(404, json=missing))

        with pytest.raises(ToolError, match="Call outlook_list_task_lists again"):
            _ = await call("outlook_list_tasks", task_list=TASK_LIST)

    async def test_the_tasks_of_another_person_are_not_offered(self) -> None:
        offered = {
            f"{tool}.{argument}"
            for tool in _TASK_TOOLS
            for argument in await _input_properties(tool)
            if any(word in argument for word in ("user", "mailbox", "owner", "person"))
        }

        assert offered == set()


_TASK_TOOLS = (
    "outlook_list_task_lists",
    "outlook_list_tasks",
    "outlook_read_task",
    "outlook_create_task",
    "outlook_update_task",
    "outlook_complete_task",
)


@asynccontextmanager
async def _modern_client(person: Person) -> AsyncGenerator[Client[FastMCPTransport]]:
    with pytest.MonkeyPatch.context() as patch:
        patch_obo(patch)
        async with Client(FastMCPTransport(_server()), elicitation_handler=person) as client:
            yield client


@functools.cache
def _server() -> FastMCP[None]:
    return build_server()


async def _input_properties(tool: str) -> Mapping[str, object]:
    async with Client(FastMCPTransport(_server()), mode="legacy") as client:
        tools = {listed.name: listed for listed in await client.list_tools()}
    return cast("Mapping[str, object]", tools[tool].input_schema["properties"])
