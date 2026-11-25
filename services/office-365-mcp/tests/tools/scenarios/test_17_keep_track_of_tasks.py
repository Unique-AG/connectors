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
from respx.models import Call

from office_365_mcp.tools import TOOL_NAMES
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
STEP_ID = "STEP1"
STEP = f"{TASK}/steps/{STEP_ID}"
STEPS = f"{ONE_TASK}/checklistItems"
LINK = f"{TASK}/links/LINK1"
LINKS = f"{ONE_TASK}/linkedResources"
FILE = f"{TASK}/attachments/FILE1"
FILES = f"{ONE_TASK}/attachments"
_STEP = {"id": STEP_ID, "displayName": "Get the numbers from Anna", "isChecked": False}
_LINK = {
    "id": "LINK1",
    "displayName": "Q3 numbers",
    "webUrl": "https://outlook.office365.com/owa/?ItemID=SYNTHETIC",
    "applicationName": "Outlook",
}
_CSV = {
    "@odata.type": "#microsoft.graph.taskFileAttachment",
    "id": "FILE1",
    "name": "Numbers.csv",
    "contentType": "text/csv",
    "size": 12,
}


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


def _task_is(graph: respx.MockRouter, task: Mapping[str, object] = _SOME_TASK) -> None:
    _ = graph.get(ONE_TASK).mock(return_value=httpx.Response(200, json=dict(task)))


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
    return _body_of(route.calls.last)


def _body_of(sent: Call) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(sent.request.content))


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
        assert "$select" not in route.calls.last.request.url.params
        assert route.calls.last.request.headers["prefer"] == 'outlook.timezone="UTC"'

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

    async def test_a_due_date_in_a_windows_zone_keeps_its_day(
        self, graph: respx.MockRouter
    ) -> None:
        windows_due = {
            "dateTime": "2026-11-27T00:00:00.0000000",
            "timeZone": "W. Europe Standard Time",
        }
        tasks = [_task("T1", "Send the Q3 report", dueDateTime=windows_due)]
        _ = graph.get(TASKS).mock(return_value=httpx.Response(200, json={"value": tasks}))

        answer = await call("outlook_list_tasks", task_list=TASK_LIST, time_zone=ZURICH)

        assert [row["due_date"] for row in _rows(answer, "tasks")] == ["2026-11-27"]

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
            "dueDateTime": {"dateTime": "2026-11-27T00:00:00", "timeZone": "Europe/Zurich"},
            "importance": "high",
        }
        assert (answer["uri"], answer["due_date"], person.asked) == (TASK, "2026-11-27", [])
        assert route.call_count == 1

    async def test_a_task_is_completed(self, graph: respx.MockRouter) -> None:
        done = _task(TASK_ID, "Send the Q3 report", status="completed")
        _list_is(graph, shared=False)
        route = graph.patch(ONE_TASK).mock(return_value=httpx.Response(200, json=done))
        person = Person()

        answer = await call("outlook_set_task_status", uri=TASK, status="completed", person=person)

        assert _sent(route) == {"status": "completed"}
        assert (answer["status"], person.asked) == ("completed", [])

    async def test_a_task_is_reopened_and_its_due_date_is_removed(
        self, graph: respx.MockRouter
    ) -> None:
        reopened = _task(TASK_ID, "Send the Q3 report")
        _list_is(graph, shared=False)
        route = graph.patch(ONE_TASK).mock(return_value=httpx.Response(200, json=reopened))
        person = Person()

        opened = await call(
            "outlook_set_task_status", uri=TASK, status="not_started", person=person
        )
        cleared = await call("outlook_update_task", uri=TASK, clear_due_date=True, person=person)

        sent: list[Call] = list(route.calls)
        assert [_body_of(one) for one in sent] == [
            {"status": "notStarted"},
            {"dueDateTime": None},
        ]
        assert (opened["status"], cleared["due_date"], person.asked) == ("not_started", None, [])


class TestPlanningATask:
    async def test_a_task_is_added_with_a_start_date_and_a_reminder(
        self, graph: respx.MockRouter
    ) -> None:
        _list_is(graph, shared=False)
        created = _task(
            TASK_ID,
            "Prepare the budget",
            startDateTime={"dateTime": "2026-11-22T23:00:00", "timeZone": "UTC"},
            reminderDateTime={"dateTime": "2026-11-26T08:00:00", "timeZone": "UTC"},
            isReminderOn=True,
        )
        route = graph.post(TASKS).mock(return_value=httpx.Response(201, json=created))

        answer = await call(
            "outlook_create_task",
            task_list=TASK_LIST,
            title="Prepare the budget",
            start_date="2026-11-23",
            reminder_at="2026-11-26T09:00:00",
            time_zone=ZURICH,
        )

        sent = _sent(route)
        assert (sent["startDateTime"], sent["reminderDateTime"], sent["isReminderOn"]) == (
            {"dateTime": "2026-11-23T00:00:00", "timeZone": "Europe/Zurich"},
            {"dateTime": "2026-11-26T08:00:00", "timeZone": "UTC"},
            True,
        )
        assert (answer["start_date"], answer["reminder_at"]) == (
            "2026-11-23",
            "2026-11-26T08:00:00Z",
        )

    async def test_a_task_repeats_every_week_on_monday(self, graph: respx.MockRouter) -> None:
        _list_is(graph, shared=False)
        series = {
            "pattern": {
                "type": "weekly",
                "interval": 1,
                "daysOfWeek": ["monday"],
                "firstDayOfWeek": "sunday",
            },
            "range": {"type": "noEnd", "startDate": "2026-11-23"},
        }
        created = _task(TASK_ID, "Send the weekly status", recurrence=series)
        route = graph.post(TASKS).mock(return_value=httpx.Response(201, json=created))

        answer = await call(
            "outlook_create_task",
            task_list=TASK_LIST,
            title="Send the weekly status",
            due_date="2026-11-23",
            repeat={"every": "week", "weekdays": ["monday"]},
            time_zone=ZURICH,
        )

        assert _sent(route)["recurrence"] == series
        assert answer["repeat"] == {"every": "week", "interval": 1, "weekdays": ["monday"]}

    async def test_a_series_on_a_weekday_of_the_month_still_reads_as_repeating(
        self, graph: respx.MockRouter
    ) -> None:
        last_friday = {
            "pattern": {
                "type": "relativeMonthly",
                "interval": 1,
                "daysOfWeek": ["friday"],
                "index": "last",
            },
            "range": {"type": "noEnd", "startDate": "2026-11-27"},
        }
        _ = graph.get(ONE_TASK).mock(
            return_value=httpx.Response(
                200, json=_task(TASK_ID, "Send the report", recurrence=last_friday)
            )
        )

        answer = await call("outlook_read_task", uri=TASK)

        assert (answer["repeats"], answer["repeat"]) == (True, None)

    async def test_a_reminder_in_the_hour_that_the_clocks_skip_is_refused(
        self, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="the clocks skip that time"):
            _ = await call(
                "outlook_create_task",
                task_list=TASK_LIST,
                title="Call the bank",
                reminder_at="2027-03-28T02:30:00",
                time_zone=ZURICH,
            )

        assert graph.calls.call_count == 0

    async def test_a_reminder_in_the_hour_that_occurs_twice_needs_an_offset(
        self, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="occurs twice"):
            _ = await call(
                "outlook_create_task",
                task_list=TASK_LIST,
                title="Call the bank",
                reminder_at="2026-10-25T02:30:00",
                time_zone=ZURICH,
            )

        assert graph.calls.call_count == 0

    async def test_a_repeating_task_with_no_due_date_is_refused(
        self, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="Give `due_date` in the same call"):
            _ = await call(
                "outlook_create_task",
                task_list=TASK_LIST,
                title="Send the weekly status",
                repeat={"every": "week"},
            )

        assert graph.calls.call_count == 0

    async def test_a_task_stops_repeating_and_its_reminder_is_turned_off(
        self, graph: respx.MockRouter
    ) -> None:
        _list_is(graph, shared=False)
        route = graph.patch(ONE_TASK).mock(return_value=httpx.Response(200, json=_SOME_TASK))

        answer = await call("outlook_update_task", uri=TASK, clear_repeat=True, clear_reminder=True)

        assert _sent(route) == {"isReminderOn": False, "recurrence": None, "reminderDateTime": None}
        assert (answer["repeat"], answer["reminder_at"]) == (None, None)

    async def test_a_task_gets_a_category(self, graph: respx.MockRouter) -> None:
        _list_is(graph, shared=False)
        tagged = _task(TASK_ID, "Send the Q3 report", categories=["Finance"])
        route = graph.patch(ONE_TASK).mock(return_value=httpx.Response(200, json=tagged))

        answer = await call("outlook_update_task", uri=TASK, categories=["Finance"])

        assert _sent(route) == {"categories": ["Finance"]}
        assert answer["categories"] == ["Finance"]

    async def test_a_task_waits_on_another_person(self, graph: respx.MockRouter) -> None:
        _list_is(graph, shared=False)
        waiting = _task(TASK_ID, "Send the Q3 report", status="waitingOnOthers")
        route = graph.patch(ONE_TASK).mock(return_value=httpx.Response(200, json=waiting))

        answer = await call("outlook_set_task_status", uri=TASK, status="waiting_on_others")

        assert _sent(route) == {"status": "waitingOnOthers"}
        assert route.calls.last.request.headers["prefer"] == 'outlook.timezone="UTC"'
        assert answer["status"] == "waiting_on_others"


class TestSteps:
    async def test_a_step_is_added_to_a_task(self, graph: respx.MockRouter) -> None:
        _list_is(graph, shared=False)
        route = graph.post(STEPS).mock(return_value=httpx.Response(201, json=_STEP))
        person = Person()

        answer = await call(
            "outlook_add_task_step", uri=TASK, text="Get the numbers from Anna", person=person
        )

        assert _sent(route) == {"displayName": "Get the numbers from Anna", "isChecked": False}
        assert (answer["uri"], answer["is_checked"], person.asked) == (STEP, False, [])

    async def test_a_step_is_checked_off(self, graph: respx.MockRouter) -> None:
        _list_is(graph, shared=False)
        checked = _STEP | {"isChecked": True, "checkedDateTime": "2026-11-24T09:00:00Z"}
        route = graph.patch(f"{STEPS}/{STEP_ID}").mock(
            return_value=httpx.Response(200, json=checked)
        )

        answer = await call("outlook_update_task_step", step=STEP, is_checked=True)

        assert _sent(route) == {"isChecked": True}
        assert answer["is_checked"] is True

    async def test_a_step_is_removed_after_the_person_agrees(self, graph: respx.MockRouter) -> None:
        _list_is(graph, shared=False)
        _task_is(graph)
        _ = graph.get(f"{STEPS}/{STEP_ID}").mock(return_value=httpx.Response(200, json=_STEP))
        route = graph.delete(f"{STEPS}/{STEP_ID}").mock(return_value=httpx.Response(204))
        person = _PersonWatchingWrites(write=route)

        answer = await call("outlook_delete_task_step", step=STEP, person=person)

        [question] = person.asked
        assert "'Get the numbers from Anna'" in question
        assert person.writes_before_each_question == [0]
        assert (answer["outcome"], route.call_count) == ("deleted", 1)

    async def test_a_declined_step_in_a_shared_list_adds_nothing(
        self, graph: respx.MockRouter
    ) -> None:
        _list_is(graph, shared=True, name="Team launch")
        route = graph.post(STEPS).mock(return_value=httpx.Response(201, json=_STEP))

        with pytest.raises(ToolError, match="Nothing was changed"):
            _ = await call(
                "outlook_add_task_step",
                uri=TASK,
                text="Call the hotel",
                person=Person(approval="no"),
            )

        assert route.call_count == 0

    async def test_a_step_change_that_names_no_change_is_refused(
        self, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="there is nothing to change"):
            _ = await call("outlook_update_task_step", step=STEP)

        assert graph.calls.call_count == 0

    async def test_a_declined_step_removal_keeps_the_step(self, graph: respx.MockRouter) -> None:
        _list_is(graph, shared=False)
        _task_is(graph)
        _ = graph.get(f"{STEPS}/{STEP_ID}").mock(return_value=httpx.Response(200, json=_STEP))
        route = graph.delete(f"{STEPS}/{STEP_ID}").mock(return_value=httpx.Response(204))

        with pytest.raises(ToolError):
            _ = await call("outlook_delete_task_step", step=STEP, person=Person(approval="no"))

        assert route.call_count == 0

    async def test_a_task_is_read_with_its_steps_links_and_files(
        self, graph: respx.MockRouter
    ) -> None:
        held = _task(
            TASK_ID,
            "Send the Q3 report",
            hasAttachments=True,
            checklistItems=[
                {"id": "STEP1", "displayName": "Get the numbers from Anna", "isChecked": True},
                {"id": "STEP2", "displayName": "Check the totals", "isChecked": False},
            ],
            linkedResources=[
                {
                    "id": "LINK1",
                    "displayName": "Q3 numbers",
                    "webUrl": "https://outlook.office365.com/owa/?ItemID=SYNTHETIC",
                    "applicationName": "Outlook",
                }
            ],
        )
        read = graph.get(ONE_TASK).mock(return_value=httpx.Response(200, json=held))
        files = {
            "value": [
                {
                    "@odata.type": "#microsoft.graph.taskFileAttachment",
                    "id": "FILE1",
                    "name": "Numbers.xlsx",
                    "contentType": "application/vnd.ms-excel",
                    "size": 2048,
                }
            ]
        }
        _ = graph.get(f"{ONE_TASK}/attachments").mock(return_value=httpx.Response(200, json=files))

        answer = await call("outlook_read_task", uri=TASK)

        assert read.calls.last.request.url.params["$expand"] == "checklistItems,linkedResources"
        assert read.calls.last.request.headers["prefer"] == 'outlook.timezone="UTC"'
        assert [(row["text"], row["is_checked"]) for row in _rows(answer, "steps")] == [
            ("Get the numbers from Anna", True),
            ("Check the totals", False),
        ]
        assert [(row["uri"], row["title"]) for row in _rows(answer, "links")] == [
            (f"{TASK}/links/LINK1", "Q3 numbers")
        ]
        assert [(row["uri"], row["name"]) for row in _rows(answer, "attachments")] == [
            (f"{TASK}/attachments/FILE1", "Numbers.xlsx")
        ]


class TestLinksAndFiles:
    async def test_a_mail_is_linked_to_a_task(self, graph: respx.MockRouter) -> None:
        _list_is(graph, shared=False)
        route = graph.post(LINKS).mock(return_value=httpx.Response(201, json=_LINK))

        answer = await call(
            "outlook_add_task_link",
            uri=TASK,
            web_url="https://outlook.office365.com/owa/?ItemID=SYNTHETIC",
            title="Q3 numbers",
        )

        assert _sent(route) == {
            "applicationName": "Outlook",
            "displayName": "Q3 numbers",
            "webUrl": "https://outlook.office365.com/owa/?ItemID=SYNTHETIC",
        }
        assert (answer["uri"], answer["title"]) == (LINK, "Q3 numbers")

    async def test_a_link_is_removed_after_the_person_agrees(self, graph: respx.MockRouter) -> None:
        _list_is(graph, shared=False)
        _task_is(graph)
        _ = graph.get(f"{LINKS}/LINK1").mock(return_value=httpx.Response(200, json=_LINK))
        route = graph.delete(f"{LINKS}/LINK1").mock(return_value=httpx.Response(204))
        person = _PersonWatchingWrites(write=route)

        answer = await call("outlook_delete_task_link", link=LINK, person=person)

        [question] = person.asked
        assert "'Q3 numbers'" in question
        assert person.writes_before_each_question == [0]
        assert (answer["outcome"], route.call_count) == ("deleted", 1)

    async def test_a_file_of_a_task_is_read(self, graph: respx.MockRouter) -> None:
        _ = graph.get(f"{FILES}/FILE1").mock(return_value=httpx.Response(200, json=_CSV))
        _ = graph.get(f"{FILES}/FILE1/$value").mock(
            return_value=httpx.Response(200, content=b"Q3,1200,1300")
        )

        with pytest.MonkeyPatch.context() as patch:
            patch_obo(patch)
            async with Client(FastMCPTransport(_server()), mode="legacy") as client:
                answer = await client.call_tool(
                    "outlook_read_task_attachment", {"attachment": FILE}
                )

        assert "Q3,1200,1300" in json.dumps([part.model_dump() for part in answer.content])

    async def test_a_file_is_removed_after_the_person_agrees(self, graph: respx.MockRouter) -> None:
        _list_is(graph, shared=False)
        _task_is(graph)
        _ = graph.get(f"{FILES}/FILE1").mock(return_value=httpx.Response(200, json=_CSV))
        route = graph.delete(f"{FILES}/FILE1").mock(return_value=httpx.Response(204))
        person = _PersonWatchingWrites(write=route)

        answer = await call("outlook_delete_task_attachment", attachment=FILE, person=person)

        [question] = person.asked
        assert "'Numbers.csv'" in question
        assert person.writes_before_each_question == [0]
        assert (answer["outcome"], route.call_count) == ("deleted", 1)

    async def test_an_address_that_is_not_https_is_not_linked(
        self, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="https"):
            _ = await call(
                "outlook_add_task_link", uri=TASK, web_url="javascript:alert(1)", title="Q3"
            )

        assert graph.calls.call_count == 0

    async def test_a_task_handle_is_not_taken_as_a_link(self, graph: respx.MockRouter) -> None:
        with pytest.raises(ToolError, match="outlook_read_task"):
            _ = await call("outlook_delete_task_link", link=TASK)

        assert graph.calls.call_count == 0

    async def test_a_file_that_is_too_large_is_not_read(self, graph: respx.MockRouter) -> None:
        large = _CSV | {"name": "Archive.zip", "size": 40 * 1024 * 1024}
        _ = graph.get(f"{FILES}/FILE1").mock(return_value=httpx.Response(200, json=large))
        download = graph.get(f"{FILES}/FILE1/$value").mock(
            return_value=httpx.Response(200, content=b"")
        )

        with pytest.raises(ToolError, match="open the task in To Do"):
            _ = await call("outlook_read_task_attachment", attachment=FILE)

        assert download.call_count == 0

    async def test_a_declined_file_removal_keeps_the_file(self, graph: respx.MockRouter) -> None:
        _list_is(graph, shared=False)
        _task_is(graph)
        _ = graph.get(f"{FILES}/FILE1").mock(return_value=httpx.Response(200, json=_CSV))
        route = graph.delete(f"{FILES}/FILE1").mock(return_value=httpx.Response(204))

        with pytest.raises(ToolError):
            _ = await call(
                "outlook_delete_task_attachment", attachment=FILE, person=Person(approval="no")
            )

        assert route.call_count == 0

    async def test_no_tool_adds_a_file_to_a_task(self) -> None:
        offered = {
            f"{tool}.{argument}"
            for tool in _TASK_TOOLS
            for argument in await _input_properties(tool)
            if any(word in argument for word in ("content", "bytes", "file"))
        }

        assert offered == set()


class TestDeletingTasks:
    async def test_a_task_is_deleted_after_the_person_agrees(self, graph: respx.MockRouter) -> None:
        _list_is(graph, shared=False)
        _task_is(graph, _task(TASK_ID, "Old report"))
        route = graph.delete(ONE_TASK).mock(return_value=httpx.Response(204))
        person = _PersonWatchingWrites(write=route)

        answer = await call("outlook_delete_task", uri=TASK, person=person)

        [question] = person.asked
        assert "'Old report'" in question
        assert person.writes_before_each_question == [0]
        assert (answer["outcome"], route.call_count) == ("deleted", 1)

    async def test_a_declined_delete_keeps_the_task(self, graph: respx.MockRouter) -> None:
        _list_is(graph, shared=False)
        _task_is(graph, _task(TASK_ID, "Send the Q3 report"))
        route = graph.delete(ONE_TASK).mock(return_value=httpx.Response(204))

        with pytest.raises(ToolError):
            _ = await call("outlook_delete_task", uri=TASK, person=Person(approval="no"))

        assert route.call_count == 0

    async def test_no_tool_moves_a_task_to_another_list(self) -> None:
        update = await _input_properties("outlook_update_task")

        assert {"task_list", "list", "destination"} & set(update) == set()


class TestLists:
    async def test_a_list_is_created(self, graph: respx.MockRouter) -> None:
        made = {"id": LIST_ID, "displayName": "Move to Bern", "isShared": False, "isOwner": True}
        route = graph.post(LISTS).mock(return_value=httpx.Response(201, json=made))
        person = Person()

        answer = await call("outlook_create_task_list", name="Move to Bern", person=person)

        assert _sent(route) == {"displayName": "Move to Bern"}
        assert (answer["uri"], answer["name"], person.asked) == (TASK_LIST, "Move to Bern", [])

    async def test_a_list_is_renamed(self, graph: respx.MockRouter) -> None:
        _list_is(graph, shared=False, name="Move to Bern")
        renamed = {"id": LIST_ID, "displayName": "Move to Basel", "isShared": False}
        route = graph.patch(ONE_LIST).mock(return_value=httpx.Response(200, json=renamed))
        person = Person()

        answer = await call(
            "outlook_rename_task_list", task_list=TASK_LIST, name="Move to Basel", person=person
        )

        assert _sent(route) == {"displayName": "Move to Basel"}
        assert (answer["name"], person.asked) == ("Move to Basel", [])

    async def test_the_built_in_tasks_list_is_not_renamed(self, graph: respx.MockRouter) -> None:
        built_in = {"id": LIST_ID, "displayName": "Tasks", "wellknownListName": "defaultList"}
        _ = graph.get(ONE_LIST).mock(return_value=httpx.Response(200, json=built_in))
        route = graph.patch(ONE_LIST).mock(return_value=httpx.Response(200, json=built_in))

        with pytest.raises(ToolError, match="does not rename these lists"):
            _ = await call("outlook_rename_task_list", task_list=TASK_LIST, name="Inbox")

        assert route.call_count == 0

    async def test_a_list_is_deleted_after_the_person_agrees(self, graph: respx.MockRouter) -> None:
        _list_is(graph, shared=False, name="Move to Basel")
        route = graph.delete(ONE_LIST).mock(return_value=httpx.Response(204))
        person = _PersonWatchingWrites(write=route)

        answer = await call("outlook_delete_task_list", task_list=TASK_LIST, person=person)

        [question] = person.asked
        assert "'Move to Basel' and every task in it" in question
        assert person.writes_before_each_question == [0]
        assert (answer["outcome"], route.call_count) == ("deleted", 1)

    async def test_a_new_list_is_not_made_twice_after_a_failure(
        self, graph: respx.MockRouter
    ) -> None:
        route = graph.post(LISTS).mock(return_value=httpx.Response(503))

        with pytest.raises(ToolError, match="outlook_list_task_lists") as raised:
            _ = await call("outlook_create_task_list", name="Move to Bern")

        assert "Do not call this tool again first" in str(raised.value)
        assert route.call_count == 1

    async def test_the_built_in_tasks_list_is_not_deleted(self, graph: respx.MockRouter) -> None:
        built_in = {"id": LIST_ID, "displayName": "Tasks", "wellknownListName": "defaultList"}
        _ = graph.get(ONE_LIST).mock(return_value=httpx.Response(200, json=built_in))
        route = graph.delete(ONE_LIST).mock(return_value=httpx.Response(204))
        person = Person()

        with pytest.raises(ToolError, match="does not delete these lists"):
            _ = await call("outlook_delete_task_list", task_list=TASK_LIST, person=person)

        assert (route.call_count, person.asked) == (0, [])


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
        _task_is(graph)
        route = graph.patch(ONE_TASK).mock(return_value=httpx.Response(200, json=_SOME_TASK))

        with pytest.raises(ToolError, match="Nothing was changed"):
            _ = await call(
                "outlook_set_task_status",
                uri=TASK,
                status="completed",
                person=Person(approval="no"),
            )

        assert route.call_count == 0

    async def test_a_change_in_a_shared_list_is_asked_in_the_newer_protocol_too(
        self, graph: respx.MockRouter
    ) -> None:
        _list_is(graph, shared=True, name="Team launch")
        _task_is(graph)
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
        assert "'Book the venue' (priority high)" in question
        assert person.writes_before_each_question == [0]
        assert route.call_count == 1

    async def test_a_repeating_task_that_moves_on_while_the_person_decides_is_not_completed(
        self, graph: respx.MockRouter
    ) -> None:
        _list_is(graph, shared=True, name="Team launch")
        this_week = _task(
            TASK_ID, "Water the plants", due_utc="2026-11-26T23:00:00", **{"@odata.etag": 'W/"1"'}
        )
        _ = graph.get(ONE_TASK).mock(return_value=httpx.Response(200, json=this_week))
        conflict = {"error": {"code": "ErrorIrresolvableConflict", "message": "Conflict."}}
        route = graph.patch(ONE_TASK).mock(return_value=httpx.Response(412, json=conflict))

        with pytest.raises(ToolError, match="The task changed while the user decided"):
            _ = await call("outlook_set_task_status", uri=TASK, status="completed")

        assert route.calls.last.request.headers["if-match"] == 'W/"1"'

    async def test_a_list_that_does_not_say_whether_it_is_shared_is_asked_about(
        self, graph: respx.MockRouter
    ) -> None:
        _list_is(graph, shared=None, name="Team launch")
        _task_is(graph)
        route = graph.patch(ONE_TASK).mock(return_value=httpx.Response(200, json=_SOME_TASK))
        person = Person()

        _ = await call("outlook_set_task_status", uri=TASK, status="completed", person=person)

        [question] = person.asked
        assert "did not report as private" in question
        assert "'Book the venue' to completed" in question
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
            _ = await call("outlook_set_task_status", uri=TASK, status="completed")

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


_TASK_TOOLS = tuple(
    sorted(name for name in TOOL_NAMES if "task" in name and name.startswith("outlook_"))
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
