import json
import re
from datetime import UTC, datetime
from typing import cast

import httpx
import pytest

from office_365_mcp.tools import TOOL_NAMES
from tests.e2e.recording import stand_in
from tests.e2e.recording.cases import case_entries
from tests.e2e.recording.families import load
from tests.e2e.recording.families import onenote as family
from tests.e2e.recording.guard import DEFAULT_CAP, Guard
from tests.e2e.recording.lint import lint_files
from tests.e2e.recording.record import check, guard_for, resolve, tool_of
from tests.e2e.recording.runbook import reads
from tests.e2e.recording.scrub import Hop, Identities, Recording, files_of, scrub
from tests.e2e.test_scenarios import Json, select

GRAPH = "https://graph.microsoft.com/v1.0"
ONENOTE_TOOLS = sorted(name for name in TOOL_NAMES if name.startswith("onenote_"))
CASES = {case_id: resolve(case_id) for case_id, _ in case_entries() if "onenote_" in case_id[:8]}
NAME_ARGUMENTS = ("name", "title", "new_name")
CREATING = frozenset(
    {"onenote_create_notebook", "onenote_create_section", "onenote_create_section_group"}
    | {"onenote_create_page", "onenote_copy_section", "onenote_copy_notebook"}
)
PAGE = "1-0f1e2d3c-4b5a-4978-8796-a5b4c3d2e1f0"
SECTION = "1-8d4f1a2b-3c5e-4f60-9a7b-2c1d0e9f8a7b"


def guard() -> Guard:
    return Guard(stand_in.UPN, frozenset(stand_in.UPNS), True, seen_seed={SECTION})


def request(method: str, path: str, body: str = "") -> httpx.Request:
    return httpx.Request(method, f"{GRAPH}{path}", content=body)


def test_every_onenote_tool_is_in_the_family_and_has_a_case() -> None:
    merged = load()
    claimed = merged.read_tools | set(merged.write_tools)
    skipped = {tool for tool in merged.unrecorded if tool.startswith("onenote_")}
    assert sorted({t for t in claimed if t.startswith("onenote_")} | skipped) == ONENOTE_TOOLS
    assert len(ONENOTE_TOOLS) == 20
    assert skipped == set()
    assert {tool_of(plan.steps[-1]) for plan in CASES.values()} == set(ONENOTE_TOOLS) - skipped


@pytest.mark.parametrize("case_id", CASES)
def test_a_case_passes_the_guard_plan_and_changes_no_seed_item(case_id: str) -> None:
    plan = CASES[case_id]
    assert check(plan, guard_for(stand_in.UPNS, plan, True, DEFAULT_CAP)) == []
    assert (plan.persona, plan.destructive, plan.external, plan.reseed) == (1, False, False, ())
    tools = [tool_of(step) for step in plan.steps]
    assert case_id.startswith(f"{tools[-1]}-")
    if reads(plan):
        assert not {t for t in tools if t in load().write_tools}
    for number, step in enumerate(plan.steps, 1):
        refs = cast("list[str]", re.findall(r"\$(\w+)", json.dumps(step.get("bind", {}))))
        assert all(r == "prev" and number > 1 or r.isdigit() and int(r) < number for r in refs)
        args = cast("Json", step.get("args", {}))
        if tool_of(step) in CREATING:
            named = next(str(args[key]) for key in NAME_ARGUMENTS if key in args)
            assert named.startswith("seed-v1 case-")


def test_the_recent_notebooks_case_waits_for_its_probe() -> None:
    assert CASES["onenote_list_recent_notebooks-recent"].needs == ("onenote_recent",)
    assert set(family.NEEDS) == set(family.PROBES) == {"onenote_recent", "onenote_seed"}


def test_a_case_that_looks_up_a_seed_notebook_waits_until_the_list_shows_them() -> None:
    waiting = {case_id for case_id, plan in CASES.items() if plan.needs == ("onenote_seed",)}
    reading = {
        case_id
        for case_id, plan in CASES.items()
        if tool_of(plan.steps[0]) == "onenote_list_notebooks"
    }
    assert waiting == reading
    assert set(CASES) - waiting == {
        "onenote_list_recent_notebooks-recent",
        "onenote_create_notebook-new",
    }
    assert family.PROBES["onenote_seed"][2] == 3
    assert "contains(tolower(displayName),'seed-v1')" in family.PROBES["onenote_seed"][1]


def test_the_group_listing_asks_for_the_wider_scope_and_the_family_waits_between_cases() -> None:
    assert CASES["onenote_list_sections-group"].scopes == ("Notes.ReadWrite.All",)
    assert [c for c, plan in CASES.items() if plan.scopes] == ["onenote_list_sections-group"]
    assert family.GAP_SECONDS == 20


def test_a_name_that_carries_a_day_uses_the_day_after_the_first_live_pass() -> None:
    named = [
        value
        for plan in CASES.values()
        for step in plan.steps
        for key, value in cast("Json", step.get("args", {})).items()
        if key in NAME_ARGUMENTS and "~" in str(value)
    ]
    assert len(named) == 6
    assert all(str(value).endswith(" ~tomorrow") for value in named)


@pytest.mark.parametrize(
    "tool", ["onenote_append_to_page", "onenote_edit_page", "onenote_rename_page"]
)
def test_a_page_write_needs_a_page_that_the_run_created(tool: str) -> None:
    made = guard()
    patch = request("POST", f"/me/onenote/pages/{PAGE}/onenotePatchContent", "[]")
    delete = request("DELETE", f"/me/onenote/pages/{PAGE}")
    assert "did not read as seed data" in str(made.refuses_request(patch, tool))
    made.saw(request("POST", f"/me/onenote/sections/{SECTION}/pages"), 201, None, {"id": PAGE})
    assert made.refuses_request(patch, tool) is None
    assert made.refuses_request(delete, "onenote_delete_page") is None
    assert "not a write path" in str(made.refuses_request(delete, tool))


def test_the_patch_path_has_one_page_segment_and_belongs_to_three_tools() -> None:
    made = guard()
    made.created.add(PAGE)
    wrong = [
        ("POST", f"/me/onenote/pages/{PAGE}/content"),
        ("PATCH", f"/me/onenote/pages/{PAGE}/onenotePatchContent"),
        ("POST", f"/me/onenote/pages/{PAGE}/x/onenotePatchContent"),
        ("POST", "/me/onenote/pages/onenotePatchContent"),
    ]
    for method, path in wrong:
        assert "not a write path" in str(
            made.refuses_request(request(method, path, "[]"), "onenote_edit_page")
        ), path
    patch = request("POST", f"/me/onenote/pages/{PAGE}/onenotePatchContent", "[]")
    assert "not a write path" in str(made.refuses_request(patch, "onenote_create_page"))
    assert "not a write path" in str(made.refuses_request(patch, "onenote_delete_page"))


def test_a_page_goes_into_a_seed_section_only() -> None:
    made = guard()
    post = request("POST", f"/me/onenote/sections/{SECTION}/pages", "<html></html>")
    stray = request("POST", "/me/onenote/sections/1-other/pages", "<html></html>")
    default = request("POST", "/me/onenote/pages", "<html></html>")
    assert made.refuses_request(post, "onenote_create_page") is None
    assert "did not read as seed data" in str(made.refuses_request(stray, "onenote_create_page"))
    assert "not a write path" in str(made.refuses_request(default, "onenote_create_page"))


def test_a_copy_goes_to_a_known_destination_only() -> None:
    made = guard()
    made.created.add(PAGE)
    path = f"/me/onenote/pages/{PAGE}/copyToSection"
    known = request("POST", path, json.dumps({"id": SECTION}))
    foreign = request("POST", path, json.dumps({"id": "1-other"}))
    assert made.refuses_request(known, "onenote_copy_page") is None
    assert "did not read as seed data" in str(made.refuses_request(foreign, "onenote_copy_page"))
    poll = request("GET", f"/me/onenote/operations/{PAGE}")
    assert made.refuses_request(poll, "onenote_get_operation") is None


def test_the_find_post_reads_only() -> None:
    post = request("POST", "/me/onenote/notebooks/getNotebookFromWebUrl", '{"webUrl": "https://x"}')
    assert (
        Guard(stand_in.UPN, frozenset(stand_in.UPNS), False).refuses_request(
            post, "onenote_find_notebook_from_url"
        )
        is None
    )
    assert (
        Guard(stand_in.UPN, frozenset(stand_in.UPNS), False).refuses_request(
            post, "onenote_list_notebooks"
        )
        is not None
    )


def hop(path: str, body: Json, method: str = "GET", status: int = 200) -> Hop:
    asked = {"method": method, "host": "graph.microsoft.com", "path": path}
    asked |= {"query": {}, "headers": {}, "json": None}
    headers = (("content-type", "application/json"),)
    return Hop(asked, f"{GRAPH}{path}", True, status, headers, json.dumps(body).encode())


def links(name: str) -> Json:
    home = re.sub(r"[@.]", "_", stand_in.UPN)
    web = f"https://contoso-my.sharepoint.com/personal/{home}/Documents/{name}"
    return {"oneNoteClientUrl": {"href": f"onenote:{web}"}, "oneNoteWebUrl": {"href": web}}


def test_the_onenote_shapes_scrub_and_pass_the_lint() -> None:
    by = {"user": {"id": stand_in.USER_ID, "displayName": "Tester Three"}}
    notebook: Json = {
        "id": f"1-{stand_in.TENANT_ID}",
        "displayName": "seed-v1 Dogfood Notes",
        "isDefault": False,
        "isShared": False,
        "userRole": "Owner",
        "createdBy": by,
        "createdDateTime": "2026-10-29T08:00:00.123Z",
        "links": links("seed-v1%20Dogfood%20Notes"),
        "self": f"{GRAPH}/users/{stand_in.USER_ID}/onenote/notebooks/1-{stand_in.TENANT_ID}",
        "sectionsUrl": f"{GRAPH}/users/{stand_in.USER_ID}/onenote/notebooks/x/sections",
        "@odata.context": f"{GRAPH}/$metadata#notebooks",
    }
    section: Json = {
        "id": SECTION,
        "displayName": "seed-v1 Planning",
        "parentNotebook": {"id": notebook["id"], "displayName": "seed-v1 Dogfood Notes"},
        "parentSectionGroup": None,
    }
    page: Json = {
        "id": PAGE,
        "title": "Launch plan",
        "level": 0,
        "order": 1,
        "createdByAppId": stand_in.TENANT_ID,
        "contentUrl": f"{GRAPH}/users/{stand_in.USER_ID}/onenote/pages/{PAGE}/content",
        "parentSection": {"id": SECTION, "displayName": "seed-v1 Planning"},
    }
    operation: Json = {
        "id": f"1-{stand_in.USER_ID}",
        "status": "completed",
        "percentComplete": "100",
        "createdDateTime": "2026-10-29T08:00:00Z",
        "lastActionDateTime": "2026-10-29T08:00:05Z",
        "resourceId": PAGE,
        "resourceLocation": f"{GRAPH}/users/{stand_in.USER_ID}/onenote/pages/{PAGE}",
        "error": {"code": "0", "message": "none"},
    }
    preview: Json = {
        "previewText": "The launch is on the first Monday of next month.",
        "previewImageUrl": f"{GRAPH}/users/{stand_in.USER_ID}/onenote/resources/{PAGE}/$value",
    }
    recent: Json = {
        "displayName": "seed-v1 Dogfood Notes",
        "lastAccessedTime": "2026-10-29T08:00:00Z",
        "sourceService": "OneDriveForBusiness",
        "links": links("seed-v1%20Dogfood%20Notes"),
    }
    found: Json = notebook | {
        "name": "seed-v1 Dogfood Notes",
        "createdTime": "2026-10-29T08:00:00Z",
    }
    hops = (
        hop("/me/onenote/notebooks", {"value": [notebook]}),
        hop("/me/onenote/sections", {"value": [section]}),
        hop("/me/onenote/pages", {"value": [page]}),
        hop(f"/me/onenote/pages/{PAGE}/preview()", preview),
        hop(
            "/me/onenote/notebooks/getRecentNotebooks(includePersonalNotebooks=true)",
            {"value": [recent]},
        ),
        hop("/me/onenote/notebooks/getNotebookFromWebUrl", found, "POST"),
        hop(f"/me/onenote/pages/{PAGE}/copyToSection", operation, "POST", 202),
    )
    recording = Recording(
        "onenote-shapes",
        "rec-tool-onenote-shapes",
        "stand-in",
        datetime(2026, 10, 29, tzinfo=UTC),
        hops,
        Identities(frozenset({stand_in.USER_ID, stand_in.UPN, stand_in.DOMAIN}), stand_in.TOKEN),
        {stand_in.UPN.casefold(): "mia"},
        frozenset(),
    )
    fixture = scrub(recording)
    assert set(fixture.dropped) == {"@odata.context"}
    files = files_of(fixture)
    assert lint_files(files, {stand_in.USER_ID, stand_in.UPN, stand_in.DOMAIN}) == []
    done = cast("Json", json.loads(files["bodies/rec-tool-onenote-shapes.07.json"]))
    assert (done["status"], done["percentComplete"]) == ("completed", "100")
    listed = cast("object", json.loads(files["bodies/rec-tool-onenote-shapes.05.json"]))
    web = str(select(listed, "value[0].links.oneNoteWebUrl.href"))
    assert web.startswith("https://contoso-my.sharepoint.com/personal/mia_")
    books = cast("object", json.loads(files["bodies/rec-tool-onenote-shapes.01.json"]))
    assert select(books, "value[0].isDefault") is False
    assert "northwind" not in b"".join(files.values()).decode().casefold()
