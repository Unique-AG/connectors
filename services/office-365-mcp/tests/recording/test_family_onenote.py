import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import httpx
import pytest
import yaml

from office_365_mcp.tools import TOOL_NAMES
from tests.integration.test_scenarios import Json, items, mapping, select
from tests.recording import stand_in
from tests.recording.cases import case_entries
from tests.recording.conftest import body_of
from tests.recording.families import load
from tests.recording.families import onenote as family
from tests.recording.guard import DEFAULT_CAP, Guard
from tests.recording.lint import lint_files
from tests.recording.record import check, guard_for, resolve, tool_of
from tests.recording.runbook import reads
from tests.recording.scrub import Hop, Identities, Recording, files_of, load_corpus, scrub

GRAPH = "https://graph.microsoft.com/v1.0"
ONENOTE_TOOLS = sorted(name for name in TOOL_NAMES if name.startswith("onenote_"))
CASES = {case_id: resolve(case_id) for case_id, _ in case_entries() if "onenote_" in case_id[:8]}
NAME_ARGUMENTS = ("name", "title", "new_name")
CREATING = frozenset(
    {"onenote_create_notebook", "onenote_create_section", "onenote_create_section_group"}
    | {"onenote_create_page", "onenote_copy_section", "onenote_copy_notebook"}
)
GROUP_WRITES = {"onenote_create_page-team-section", "onenote_copy_notebook-team"}
GROUP_CASES = {c for c, plan in CASES.items() if plan.needs == ("onenote_group",)}
BIG_CASES = {"onenote_read_page-big"}
GROUP = "5d4c3b2a-1f0e-4d9c-8b7a-6f5e4d3c2b1a"
NOTEBOOK = "1-5d4c3b2a-1f0e-4d9c-8b7a-6f5e4d3c2b1b"
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
    assert (plan.persona, plan.destructive, plan.external, plan.reseed) == (
        1,
        False,
        case_id in GROUP_WRITES,
        (),
    )
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
    assert set(family.NEEDS) == set(family.PROBES)
    assert set(family.NEEDS) == {"onenote_recent", "onenote_seed", "onenote_group", "onenote_big"}


def test_a_case_that_looks_up_a_seed_notebook_waits_until_the_list_shows_them() -> None:
    waiting = {case_id for case_id, plan in CASES.items() if plan.needs == ("onenote_seed",)}
    reading = {
        case_id
        for case_id, plan in CASES.items()
        if tool_of(plan.steps[0]) == "onenote_list_notebooks"
    }
    assert reading <= waiting
    assert waiting - reading == {"onenote_list_pages-created-after", "onenote_list_pages-window"}
    assert (
        set(CASES) - waiting
        == {
            "onenote_list_recent_notebooks-recent",
            "onenote_create_notebook-new",
        }
        | GROUP_CASES
        | BIG_CASES
    )
    assert family.PROBES["onenote_seed"][2] == 3
    assert "contains(tolower(displayName),'seed-v1')" in family.PROBES["onenote_seed"][1]


def test_the_group_listing_asks_for_the_wider_scope_and_the_family_waits_between_cases() -> None:
    assert CASES["onenote_list_sections-group"].scopes == ("Notes.ReadWrite.All",)
    scoped = {c for c, plan in CASES.items() if plan.scopes}
    assert scoped == {"onenote_list_sections-group"} | GROUP_CASES
    assert all(CASES[c].scopes == ("Notes.ReadWrite.All", "Group.Read.All") for c in GROUP_CASES)
    assert len(GROUP_CASES) == 6
    assert family.GAP_SECONDS == 20


def test_a_name_that_carries_a_day_uses_the_day_after_the_first_live_pass() -> None:
    named = [
        value
        for plan in CASES.values()
        for step in plan.steps
        for key, value in cast("Json", step.get("args", {})).items()
        if key in NAME_ARGUMENTS and "~" in str(value)
    ]
    assert len(named) == 8
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
    done = cast("Json", json.loads(body_of(files, "rec-tool-onenote-shapes.07")))
    assert (done["status"], done["percentComplete"]) == ("completed", "100")
    listed = cast("object", json.loads(body_of(files, "rec-tool-onenote-shapes.05")))
    web = str(select(listed, "value[0].links.oneNoteWebUrl.href"))
    assert web.startswith("https://contoso-my.sharepoint.com/personal/mia_")
    books = cast("object", json.loads(body_of(files, "rec-tool-onenote-shapes.01")))
    assert select(books, "value[0].isDefault") is False
    assert "northwind" not in b"".join(files.values()).decode().casefold()


def test_a_page_goes_into_a_team_section_when_the_run_read_both_ids_and_nothing_else_does() -> None:
    path = f"/groups/{GROUP}/onenote/sections/{SECTION}/pages"
    post = request("POST", path, "<html></html>")
    made = guard()
    assert "did not read as seed data" in str(made.refuses_request(post, "onenote_create_page"))
    made.seen_seed.add(GROUP)
    assert made.refuses_request(post, "onenote_create_page") is None
    stray = request("POST", f"/groups/{GROUP}/onenote/sections/1-other/pages", "<html></html>")
    assert "did not read as seed data" in str(made.refuses_request(stray, "onenote_create_page"))
    for tool in ("onenote_append_to_page", "onenote_copy_page", "onenote_delete_page"):
        assert "outside /v1.0/me/" in str(made.refuses_request(post, tool))
    patch = request("PATCH", path, "<html></html>")
    assert "outside /v1.0/me/" in str(made.refuses_request(patch, "onenote_create_page"))
    default = request("POST", f"/groups/{GROUP}/onenote/pages", "<html></html>")
    assert "outside /v1.0/me/" in str(made.refuses_request(default, "onenote_create_page"))


def test_a_copy_into_a_team_names_a_group_that_the_run_read_as_seed_data() -> None:
    path = f"/me/onenote/notebooks/{NOTEBOOK}/copyNotebook"
    made = guard()
    made.seen_seed.add(NOTEBOOK)
    into = request("POST", path, json.dumps({"groupId": GROUP, "renameAs": "seed-v1 case-copy"}))
    assert "did not read as seed data" in str(made.refuses_request(into, "onenote_copy_notebook"))
    made.seen_seed.add(GROUP)
    assert made.refuses_request(into, "onenote_copy_notebook") is None
    other = request("POST", path, json.dumps({"groupId": "00000000-0000-4000-8000-000000000000"}))
    assert "did not read as seed data" in str(made.refuses_request(other, "onenote_copy_notebook"))


def test_a_name_that_a_case_selects_or_expects_is_corpus_text() -> None:
    wanted = {
        name
        for plan in CASES.values()
        for step in plan.steps
        for name in cast(
            "list[str]", re.findall(r"\[(?:name|display_name)=([^\]\"]+)\]", json.dumps(step))
        )
    }
    for plan in CASES.values():
        for step in plan.steps:
            result = mapping(mapping(step.get("expect", {})).get("result", {}))
            wanted |= {
                str(value)
                for value in result.values()
                if str(value).startswith("seed-v1 ") and "case-" not in str(value)
            }
    assert wanted > {"seed-v1 team", "seed-v1 Shared Notes", "seed-v1 Team notes"}
    assert sorted(wanted - load_corpus().strings) == []


@pytest.mark.parametrize("case", ["onenote_list_pages-team", "onenote_read_page-team"])
def test_a_team_page_is_listed_through_its_section_and_not_through_the_account_index(
    case: str,
) -> None:
    listing = mapping(CASES[case].steps[2])
    assert tool_of(CASES[case].steps[2]) == "onenote_list_pages"
    assert "group" not in mapping(listing["bind"])
    assert "sections[name=seed-v1 Team notes]" in str(mapping(listing["bind"])["section"])


def test_the_group_cases_name_what_the_seed_creates() -> None:
    path = Path(stand_in.__file__).parents[2] / "scripts/dogfood/seed/corpus/onenote.yaml"
    corpus = mapping(cast("object", yaml.safe_load(path.read_text())))
    notebook = mapping(items(corpus["group_notebooks"])[0])
    section = mapping(items(notebook["sections"])[0])
    page = mapping(items(section["pages"])[0])
    assert f"seed-v1 {notebook['name']}" == "seed-v1 Shared Notes"
    assert f"seed-v1 {section['name']}" == "seed-v1 Team notes"
    assert f"seed-v1 {page['title']}" == "seed-v1 Team plan"
    size = mapping(corpus["big_page"])["size"]
    assert size == 900_000
    assert cast("int", size) < 1024 * 1024


def test_a_group_notebook_listing_scrubs_and_passes_the_lint() -> None:
    web = "https://contoso.sharepoint.com/sites/seedteam/SiteAssets/seed-v1%20Shared%20Notes"
    notebook: Json = {
        "id": NOTEBOOK,
        "displayName": "seed-v1 Shared Notes",
        "isDefault": False,
        "isShared": True,
        "userRole": "Owner",
        "createdBy": {"user": {"id": stand_in.USER_ID, "displayName": "Tester Three"}},
        "createdDateTime": "2026-10-29T08:00:00.123Z",
        "links": {"oneNoteWebUrl": {"href": web}, "oneNoteClientUrl": {"href": f"onenote:{web}"}},
        "self": f"{GRAPH}/groups/{GROUP}/onenote/notebooks/{NOTEBOOK}",
    }
    path = f"/groups/{GROUP}/onenote/notebooks"
    recording = Recording(
        "group-notebook",
        "rec-tool-group-notebook",
        "stand-in",
        datetime(2026, 10, 29, tzinfo=UTC),
        (hop(path, {"value": [notebook]}),),
        Identities(frozenset({stand_in.USER_ID, stand_in.UPN, stand_in.DOMAIN}), stand_in.TOKEN),
        {stand_in.UPN.casefold(): "mia"},
        frozenset(),
    )
    fixture = scrub(recording)
    files = files_of(fixture)
    assert fixture.dropped == {}
    assert lint_files(files, {stand_in.USER_ID, stand_in.UPN, stand_in.DOMAIN}) == []
    found = cast("Json", json.loads(body_of(files, "rec-tool-group-notebook.01")))
    assert select(found, "value[0].displayName") == "seed-v1 Shared Notes"
    assert select(found, "value[0].isShared") is True
    assert GROUP not in b"".join(files.values()).decode()


@pytest.mark.parametrize(
    ("tool", "path", "allowed"),
    [
        ("onenote_list_notebooks", f"/groups/{GROUP}/onenote/notebooks", True),
        ("onenote_list_sections", f"/groups/{GROUP}/onenote/notebooks/{NOTEBOOK}/sections", True),
        ("onenote_read_page", f"/groups/{GROUP}/onenote/pages/1-p/content", True),
        ("onenote_read_page", f"/groups/{GROUP}/onenote/pages/1-p", True),
        ("onenote_read_page", f"/groups/{GROUP}/onenote/pages/1-p/children", False),
        ("onenote_list_pages", f"/groups/{GROUP}/onenote/pages/1-p", False),
        ("onenote_create_page", f"/groups/{GROUP}/onenote/notebooks/{NOTEBOOK}", True),
        ("onenote_create_page", f"/groups/{GROUP}/onenote/notebooks/{NOTEBOOK}/sections", False),
        ("onenote_read_page", f"/groups/{GROUP}/onenote/notebooks/{NOTEBOOK}", False),
        ("onenote_read_page", f"/groups/{GROUP}/members", False),
        ("onenote_read_page", f"/groups/{GROUP}/calendarView", False),
        ("onenote_list_pages", f"/groups/{GROUP}/onenote/pages/1-p/content", False),
        ("outlook_list_events", f"/groups/{GROUP}/onenote/notebooks", False),
        ("sharepoint_browse_folder", f"/groups/{GROUP}/onenote/notebooks", False),
        ("onenote_list_notebooks", f"/groups/{GROUP}/drive/root", False),
    ],
)
def test_a_group_is_read_by_a_named_tool_on_a_named_path(
    tool: str, path: str, allowed: bool
) -> None:
    made = guard()
    assert (made.refuses_request(request("GET", path, ""), tool) is None) is allowed
