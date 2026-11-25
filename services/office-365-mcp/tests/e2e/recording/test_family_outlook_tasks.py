import base64
import importlib.util
import json
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import cast

import httpx
import pytest
import yaml

from office_365_mcp.tools import TOOL_NAMES
from tests.e2e.recording import stand_in
from tests.e2e.recording.conftest import body_of
from tests.e2e.recording.families import load, merge
from tests.e2e.recording.families import outlook_tasks as family
from tests.e2e.recording.guard import DEFAULT_CAP, Guard
from tests.e2e.recording.lint import lint_files
from tests.e2e.recording.record import check, guard_for, resolve, tool_of
from tests.e2e.recording.scrub import SEED, Hop, Identities, Recording, files_of, scrub
from tests.e2e.test_scenarios import Json, mapping, select


def seed_tasks() -> ModuleType:
    sys.path.append(str(SEED))
    found = importlib.util.spec_from_file_location(
        "seed_outlook_tasks", SEED / "families/outlook_tasks.py"
    )
    assert found is not None
    assert found.loader is not None
    module = importlib.util.module_from_spec(found)
    found.loader.exec_module(module)
    return module


seed_family = seed_tasks()
SEED_PHASES = cast("tuple[str, ...]", seed_family.PHASES)
BRIEF = cast("Mapping[str, bytes]", seed_family.ASSETS)["seed-v1 Launch brief.docx"]
DOCX = cast("str", seed_family.DOCX)
GRAPH = "https://graph.microsoft.com/v1.0"
CASE_FILE = Path(__file__).parent / "cases" / "outlook-tasks.yaml"
OWN_CASES = cast("Json", yaml.safe_load(CASE_FILE.read_text()))
CASES = {case_id: resolve(case_id) for case_id in OWN_CASES}
TOOLS = frozenset(
    {"outlook_list_task_lists", "outlook_list_tasks", "outlook_read_task"}
    | {"outlook_read_task_attachment", "outlook_create_task_list", "outlook_rename_task_list"}
    | {"outlook_delete_task_list", "outlook_create_task", "outlook_update_task"}
    | {"outlook_set_task_status", "outlook_delete_task", "outlook_add_task_step"}
    | {"outlook_update_task_step", "outlook_delete_task_step", "outlook_add_task_link"}
    | {"outlook_delete_task_link", "outlook_delete_task_attachment"}
)
CREATING = frozenset({"outlook_create_task_list", "outlook_create_task", "outlook_add_task_step"})
LIST = "AAMkLIST"
TASK = "AAMkTASK"
ITEM = "AAMkITEM"
TASK_PATH = f"/me/todo/lists/{LIST}/tasks/{TASK}"


def guard() -> Guard:
    return Guard(stand_in.UPN, frozenset(stand_in.UPNS), True)


def request(method: str, path: str, body: str = "") -> httpx.Request:
    return httpx.Request(method, f"{GRAPH}{path}", content=body)


def test_the_family_claims_exactly_the_17_to_do_tools_and_leaves_none_unrecorded() -> None:
    alone = merge([family])
    assert alone.read_tools | set(alone.write_tools) == TOOLS
    assert set(TOOL_NAMES) >= TOOLS
    assert not TOOLS & set(load().unrecorded)
    assert set(family.CREATED_ONLY) <= set(family.WRITE_TOOLS)


def test_every_tool_has_a_case_and_every_case_ends_in_its_tool() -> None:
    assert {tool_of(plan.steps[-1]) for plan in CASES.values()} == TOOLS
    for case_id, plan in CASES.items():
        assert case_id.startswith(f"{tool_of(plan.steps[-1])}-")


@pytest.mark.parametrize("case_id", CASES)
def test_a_case_passes_the_guard_plan_and_names_each_item_that_it_creates(case_id: str) -> None:
    plan = CASES[case_id]
    assert check(plan, guard_for(stand_in.UPNS, plan, True, DEFAULT_CAP)) == []
    assert plan.persona == 1
    assert not plan.external
    for step in plan.steps:
        if tool_of(step) in CREATING:
            args = mapping(step.get("args", {}))
            named = args.get("name") or args.get("title") or args.get("text")
            assert str(named).startswith("seed-v1 case-"), case_id


def test_only_the_attachment_delete_consumes_seed_data_and_it_reseeds_the_to_do_phase() -> None:
    consuming = {case_id: plan.reseed for case_id, plan in CASES.items() if plan.destructive}
    assert consuming == {"outlook_delete_task_attachment-old-brief": ("todo", "todo-files")}
    assert {"todo", "todo-files"} <= set(SEED_PHASES)


def test_a_task_write_needs_a_task_that_the_run_created() -> None:
    made = guard()
    patch = request("PATCH", TASK_PATH, json.dumps({"status": "completed"}))
    made.seen_seed.update({LIST, TASK})
    assert "did not create" in str(made.refuses_request(patch, "outlook_set_task_status"))
    made.saw(request("POST", f"/me/todo/lists/{LIST}/tasks"), 201, None, {"id": TASK})
    assert made.refuses_request(patch, "outlook_set_task_status") is None
    assert made.refuses_request(patch, "outlook_update_task") is None
    assert "not a write path" in str(made.refuses_request(patch, "outlook_delete_task"))


def test_a_step_write_needs_a_step_that_the_run_created() -> None:
    made = guard()
    made.created.update({LIST, TASK})
    path = f"{TASK_PATH}/checklistItems/{ITEM}"
    patch = request("PATCH", path, json.dumps({"isChecked": True}))
    assert "did not create" in str(made.refuses_request(patch, "outlook_update_task_step"))
    made.saw(request("POST", f"{TASK_PATH}/checklistItems"), 201, None, {"id": ITEM})
    assert made.refuses_request(patch, "outlook_update_task_step") is None
    assert made.refuses_request(request("DELETE", path), "outlook_delete_task_step") is None


def test_a_seed_list_takes_a_new_task_but_is_never_renamed_or_deleted() -> None:
    made = guard()
    made.saw(
        request("GET", "/me/todo/lists"),
        200,
        None,
        {"value": [{"id": LIST, "displayName": "seed-v1 Launch plan"}]},
    )
    post = request("POST", f"/me/todo/lists/{LIST}/tasks", json.dumps({"title": "seed-v1 case-x"}))
    assert made.refuses_request(post, "outlook_create_task") is None
    rename = request("PATCH", f"/me/todo/lists/{LIST}", json.dumps({"displayName": "x"}))
    assert "did not create" in str(made.refuses_request(rename, "outlook_rename_task_list"))
    delete = request("DELETE", f"/me/todo/lists/{LIST}")
    assert "did not create" in str(made.refuses_request(delete, "outlook_delete_task_list"))
    stray = request("POST", "/me/todo/lists/AAMkOTHER/tasks", json.dumps({"title": "x"}))
    assert "did not read as seed data" in str(made.refuses_request(stray, "outlook_create_task"))


def test_an_attachment_is_deleted_only_when_the_run_read_it_as_seed_data() -> None:
    made = guard()
    made.seen_seed.update({LIST, TASK})
    delete = request("DELETE", f"{TASK_PATH}/attachments/{ITEM}")
    assert "did not read as seed data" in str(
        made.refuses_request(delete, "outlook_delete_task_attachment")
    )
    listed = {"value": [{"id": ITEM, "name": "seed-v1 Old brief.docx"}]}
    made.saw(request("GET", f"{TASK_PATH}/attachments"), 200, None, listed)
    assert made.refuses_request(delete, "outlook_delete_task_attachment") is None


def hop(path: str, body: Json, method: str = "GET", status: int = 200) -> Hop:
    asked = {"method": method, "host": "graph.microsoft.com", "path": path}
    asked |= {"query": {}, "headers": {}, "json": None}
    headers = (("content-type", "application/json"),)
    return Hop(asked, f"{GRAPH}{path}", True, status, headers, json.dumps(body).encode())


def test_the_to_do_shapes_scrub_and_pass_the_lint() -> None:
    task_list: Json = {
        "id": LIST,
        "displayName": "seed-v1 Launch plan",
        "isOwner": True,
        "isShared": False,
        "wellknownListName": "none",
        "@odata.etag": 'W/"m1fdwWoFiE2YS9yegTKoYwAAAAAAEg=="',
    }
    task: Json = {
        "id": TASK,
        "title": "seed-v1 Water the office plants",
        "status": "notStarted",
        "importance": "normal",
        "isReminderOn": True,
        "categories": ["seed-v1"],
        "hasAttachments": True,
        "createdDateTime": "2026-10-29T08:00:00.1234567Z",
        "lastModifiedDateTime": "2026-10-29T08:00:00.1234567Z",
        "bodyLastModifiedDateTime": "2026-10-29T08:00:00.1234567Z",
        "body": {"content": "The plants need water once a week.", "contentType": "text"},
        "dueDateTime": {"dateTime": "2026-11-02T00:00:00.0000000", "timeZone": "UTC"},
        "reminderDateTime": {"dateTime": "2026-11-01T09:00:00.0000000", "timeZone": "UTC"},
        "recurrence": {
            "pattern": {
                "type": "weekly",
                "interval": 1,
                "month": 0,
                "dayOfMonth": 0,
                "daysOfWeek": ["monday"],
                "firstDayOfWeek": "sunday",
                "index": "first",
            },
            "range": {
                "type": "noEnd",
                "startDate": "2026-11-02",
                "endDate": "0001-01-01",
                "recurrenceTimeZone": "UTC",
                "numberOfOccurrences": 0,
            },
        },
        "checklistItems": [
            {
                "id": ITEM,
                "displayName": "seed-v1 Check the dates",
                "isChecked": True,
                "checkedDateTime": "2026-10-29T08:00:00Z",
                "createdDateTime": "2026-10-29T08:00:00Z",
            }
        ],
        "linkedResources": [
            {
                "id": ITEM,
                "displayName": "seed-v1 Launch site",
                "webUrl": "https://contoso.sharepoint.com/sites/launch",
                "applicationName": "Dogfood",
                "externalId": "AAMkEXTERNAL",
            }
        ],
    }
    attachment: Json = {
        "@odata.type": "#microsoft.graph.taskFileAttachment",
        "id": ITEM,
        "name": "seed-v1 Launch brief.docx",
        "contentType": DOCX,
        "size": len(BRIEF),
        "lastModifiedDateTime": "2026-10-29T08:00:00Z",
        "contentBytes": base64.b64encode(BRIEF).decode("ascii"),
    }
    hops = (
        hop("/me/todo/lists", {"value": [task_list]}),
        hop(f"/me/todo/lists/{LIST}/tasks/{TASK}", task),
        hop(f"/me/todo/lists/{LIST}/tasks/{TASK}/attachments/{ITEM}", attachment),
    )
    recording = Recording(
        "todo-shapes",
        "rec-tool-todo-shapes",
        "stand-in",
        datetime(2026, 10, 29, tzinfo=UTC),
        hops,
        Identities(frozenset({stand_in.USER_ID, stand_in.UPN, stand_in.DOMAIN}), stand_in.TOKEN),
        {stand_in.UPN.casefold(): "mia"},
        frozenset(),
    )
    fixture = scrub(recording)
    assert set(fixture.dropped) == set()
    files = files_of(fixture)
    assert lint_files(files, {stand_in.USER_ID, stand_in.UPN, stand_in.DOMAIN}) == []
    lists = cast("object", json.loads(body_of(files, "rec-tool-todo-shapes.01")))
    assert select(lists, "value[0].displayName") == "seed-v1 Launch plan"
    assert select(lists, "value[0].wellknownListName") == "none"
    read = cast("object", json.loads(body_of(files, "rec-tool-todo-shapes.02")))
    assert select(read, "title") == "seed-v1 Water the office plants"
    assert select(read, "recurrence.pattern.daysOfWeek") == ["monday"]
    assert select(read, "checklistItems[0].isChecked") is True
    assert select(read, "linkedResources[0].displayName") == "seed-v1 Launch site"
    filed = cast("object", json.loads(body_of(files, "rec-tool-todo-shapes.03")))
    assert select(filed, "contentBytes") == attachment["contentBytes"]
