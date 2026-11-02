import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import httpx
import pytest
import yaml

from tests.e2e.recording import cases as cases_module
from tests.e2e.recording import stand_in
from tests.e2e.recording.conftest import record_on
from tests.e2e.recording.families import load
from tests.e2e.recording.guard import GRAPH_HOST, READ_TOOLS, WRITE_TOOLS, Guard
from tests.e2e.recording.lint import lint_files
from tests.e2e.recording.record import describe, guard_for, resolve
from tests.e2e.recording.scrub import Fixture, Hop, Identities, Recording, files_of, scrub
from tests.e2e.test_scenarios import Json, items, mapping

CASES = mapping(
    cast(
        "object",
        yaml.safe_load((Path(cases_module.__file__).parent / "sharepoint.yaml").read_text()),
    )
)
GRAPH = f"https://{GRAPH_HOST}/v1.0"
ITEM = "01SEEDITEMAAAAAAAAAAAAAAAAAAAAAAAA"
TARGET = "01TARGETAAAAAAAAAAAAAAAAAAAAAAAAAA"
PATH = f"/drives/{stand_in.DRIVE_ID}/items"
LINK = f"https://{stand_in.MY_HOST}{stand_in.ONEDRIVE_PATH}/:w:/g/personal"
CREATING = frozenset(
    {"sharepoint_create_folder", "sharepoint_copy_item", "sharepoint_create_text_file"}
)
KEEPING_THE_SEED = CREATING | {"sharepoint_invite"}
EXTERNAL = frozenset({"sharepoint_create_share_link", "sharepoint_invite"})
NEW_FILE = f"{PATH}/{ITEM}:/seed-v1 case-x.txt:/content"
SHARE = "/shares/u!aHR0cHM6Ly9jb250b3NvLXRlc3QvYQ/driveItem"


def last_tool(case: str) -> str:
    return str(mapping(items(mapping(CASES[case])["chain"])[-1])["tool"])


def guard() -> Guard:
    return Guard(
        stand_in.UPN,
        frozenset(stand_in.UPNS),
        True,
        me_id=stand_in.USER_ID,
        drive_ids=frozenset({stand_in.DRIVE_ID}),
        seen_seed={ITEM, TARGET},
    )


FOLDER = "01NEWFOLDERAAAAAAAAAAAAAAAAAAAAAAA"


def refusal_of(made: Guard, item: str, body: Json) -> str | None:
    request = httpx.Request("POST", f"{GRAPH}{PATH}/{item}/invite", content=json.dumps(body))
    return made.refuses_request(request, "sharepoint_invite")


def refusal(tool: str, method: str, path: str, body: Json | None = None) -> str | None:
    request = httpx.Request(method, f"{GRAPH}{path}", content=json.dumps(body or {}))
    return guard().refuses_request(request, tool)


class TestCases:
    @pytest.mark.parametrize("case", list(CASES))
    def test_the_guard_plan_allows_every_step(self, case: str) -> None:
        plan = resolve(case)
        lines = describe(plan, guard_for(stand_in.UPNS, plan, True, 40))
        assert len(lines) == len(plan.steps) + 1
        assert not [line for line in lines if "REFUSED" in line]

    def test_every_allowed_tool_has_a_case_and_the_others_stay_off_the_list(self) -> None:
        mine = {t for t in (*READ_TOOLS, *WRITE_TOOLS) if t == "get_me" or "sharepoint" in t}
        assert mine == {last_tool(case) for case in CASES}

    def test_a_write_case_consumes_a_seed_file_and_reseeds_the_files(self) -> None:
        for case in CASES:
            plan = resolve(case)
            wrote = last_tool(case) in set(WRITE_TOOLS) - KEEPING_THE_SEED
            assert plan.destructive == wrote
            assert plan.reseed == (("files",) if wrote else ())
            assert plan.external == (last_tool(case) in EXTERNAL)
            assert plan.persona == 1

    def test_a_case_that_needs_the_index_waits_for_the_seed_files(self) -> None:
        searching = [c for c in CASES if "sharepoint_search_files" in json.dumps(CASES[c])]
        assert searching
        assert all(resolve(c).needs == ("sharepoint-seed-files",) for c in searching)
        assert {"sharepoint-seed-files"} <= set(load().probes) & set(load().needs)

    def test_a_case_names_no_address(self) -> None:
        assert "@" not in json.dumps(CASES)

    def test_a_case_names_what_it_creates_with_its_own_case_tag(self) -> None:
        naming = CREATING | {"sharepoint_rename_item"}
        names = [
            (case, str(mapping(mapping(step)["args"])["name"]))
            for case in CASES
            for step in items(mapping(CASES[case])["chain"])
            if mapping(step)["tool"] in naming
        ]
        assert {case for case, _ in names} >= {c for c in CASES if last_tool(c) in CREATING}
        assert all(name.startswith(f"seed-v1 case-{case}") for case, name in names)

    def test_a_move_takes_its_target_from_a_folder_tool_and_never_from_a_search(self) -> None:
        chain = [
            mapping(step) for step in items(mapping(CASES["sharepoint_move_item-budget"])["chain"])
        ]
        target = str(mapping(chain[-1]["bind"])["to_folder"])
        source = chain[int(target[1:].partition(".")[0]) - 1]
        assert source["tool"] == "sharepoint_create_folder"
        assert target.endswith(".uri")

    def test_a_case_records_against_the_stand_in_and_replays(self) -> None:
        for case in ("get_me-profile", "sharepoint_read_file-docx"):
            outcome = record_on(case)
            assert outcome.fixture.name == f"rec-tool-{case}"
            assert outcome.unmet == []


class TestGuardRules:
    @pytest.mark.parametrize(
        ("tool", "method", "path", "body"),
        [
            ("sharepoint_rename_item", "PATCH", f"{PATH}/{ITEM}", {"name": "seed-v1 case-x.txt"}),
            (
                "sharepoint_move_item",
                "PATCH",
                f"{PATH}/{ITEM}",
                {"parentReference": {"id": TARGET}},
            ),
            ("sharepoint_delete_item", "DELETE", f"{PATH}/{ITEM}", None),
            (
                "sharepoint_create_folder",
                "POST",
                f"{PATH}/{ITEM}/children",
                {"name": "seed-v1 case-x", "folder": {}},
            ),
            (
                "sharepoint_copy_item",
                "POST",
                f"{PATH}/{ITEM}/copy",
                {"parentReference": {"driveId": stand_in.DRIVE_ID, "id": TARGET}, "name": "x"},
            ),
            (
                "sharepoint_create_share_link",
                "POST",
                f"{PATH}/{ITEM}/createLink",
                {"type": "view", "scope": "organization"},
            ),
            ("sharepoint_create_text_file", "PUT", NEW_FILE, None),
        ],
    )
    def test_a_seed_item_takes_its_own_write(
        self, tool: str, method: str, path: str, body: Json | None
    ) -> None:
        assert refusal(tool, method, path, body) is None

    @pytest.mark.parametrize(
        ("tool", "method", "path", "body", "reason"),
        [
            ("sharepoint_rename_item", "PATCH", f"{PATH}/01OTHER", {}, "did not read as seed"),
            (
                "sharepoint_move_item",
                "PATCH",
                f"{PATH}/{ITEM}",
                {"parentReference": {"id": "01OTHER"}},
                "did not read as seed",
            ),
            (
                "sharepoint_create_share_link",
                "POST",
                f"{PATH}/{ITEM}/createLink",
                {"scope": "anonymous"},
                "no recording may do",
            ),
            ("sharepoint_rename_item", "PATCH", f"/drives/other/items/{ITEM}", {}, "outside"),
            (
                "sharepoint_create_folder",
                "POST",
                f"{PATH}/01OTHER/children",
                {"name": "seed-v1 case-x"},
                "did not read as seed",
            ),
            (
                "sharepoint_copy_item",
                "POST",
                f"{PATH}/{ITEM}/copy",
                {"parentReference": {"id": "01OTHER"}},
                "did not read as seed",
            ),
            ("sharepoint_create_folder", "PATCH", f"{PATH}/{ITEM}", {}, "not a write path"),
            ("sharepoint_copy_item", "POST", f"{PATH}/{ITEM}/children", {}, "not a write path"),
            ("sharepoint_rename_item", "DELETE", f"{PATH}/{ITEM}", None, "not a write path"),
            ("sharepoint_delete_item", "PATCH", f"{PATH}/{ITEM}", {}, "not a write path"),
            ("sharepoint_rename_item", "POST", f"{PATH}/{ITEM}/children", {}, "not a write path"),
            (
                "sharepoint_create_share_link",
                "POST",
                f"{PATH}/{ITEM}/invite",
                {},
                "not a write path",
            ),
            ("sharepoint_rename_item", "POST", f"{PATH}/{ITEM}/copy", {}, "not a write path"),
            (
                "sharepoint_create_text_file",
                "PUT",
                NEW_FILE.replace("/01", "/01OTHER", 1),
                None,
                "did not read as seed",
            ),
            (
                "sharepoint_create_text_file",
                "PUT",
                NEW_FILE.replace("seed-v1 case-x", "notes"),
                None,
                "not a write path",
            ),
            (
                "sharepoint_create_text_file",
                "PUT",
                f"{PATH}/{ITEM}/seed-v1 case-x.txt/content",
                None,
                "not a write path",
            ),
            (
                "sharepoint_create_text_file",
                "POST",
                f"{PATH}/{ITEM}/children",
                {},
                "not a write path",
            ),
            ("sharepoint_rename_item", "PUT", NEW_FILE, None, "not a write path"),
            ("sharepoint_resolve_url", "PUT", NEW_FILE, None, "may not make here"),
        ],
    )
    def test_anything_else_is_refused(
        self, tool: str, method: str, path: str, body: Json | None, reason: str
    ) -> None:
        assert reason in str(refusal(tool, method, path, body))

    def test_an_invitation_goes_to_a_test_user_on_an_item_that_the_run_created(self) -> None:
        made = guard()
        made.created.add(FOLDER)
        anna = stand_in.UPNS[1]
        body = {"recipients": [{"email": anna}], "roles": ["read"], "sendInvitation": False}
        assert refusal_of(made, FOLDER, body) is None
        outside = {"recipients": [{"email": "x@outside.example"}], "roles": ["read"]}
        assert "body holds an address that is not a test user" in str(
            refusal_of(made, FOLDER, outside)
        )
        assert "did not create" in str(refusal_of(made, ITEM, body))
        assert "did not create" in str(refusal_of(made, "01NEVERSEENAAAAAAAAAAAAAAAAAAAAAAA", body))

    def test_the_invite_glob_belongs_to_the_invite_tool_alone(self) -> None:
        made = guard()
        made.created.add(FOLDER)
        invite = f"{PATH}/{FOLDER}/invite"
        for tool in ("sharepoint_create_folder", "sharepoint_move_item", "sharepoint_rename_item"):
            request = httpx.Request("POST", f"{GRAPH}{invite}", content=b"{}")
            assert "not a write path" in str(made.refuses_request(request, tool))
        for method in ("PATCH", "DELETE", "PUT"):
            request = httpx.Request(method, f"{GRAPH}{invite}", content=b"{}")
            assert "not a write path" in str(made.refuses_request(request, "sharepoint_invite"))

    def test_a_move_into_a_folder_that_the_run_created_is_allowed(self) -> None:
        made = guard()
        made.created.add("01NEWFOLDERAAAAAAAAAAAAAAAAAAAAAAA")
        body = {"parentReference": {"id": "01NEWFOLDERAAAAAAAAAAAAAAAAAAAAAAA"}}
        request = httpx.Request("PATCH", f"{GRAPH}{PATH}/{ITEM}", content=json.dumps(body))
        assert made.refuses_request(request, "sharepoint_move_item") is None

    @pytest.mark.parametrize(
        ("tool", "path", "allowed"),
        [
            ("sharepoint_search_sites", "/sites", True),
            ("sharepoint_search_sites", "/sites/contoso.sharepoint.com", False),
            ("sharepoint_search_sites", SHARE, False),
            ("sharepoint_search_files", "/sites", False),
            ("sharepoint_resolve_url", SHARE, True),
            ("sharepoint_resolve_url", SHARE.replace("driveItem", "permissions"), False),
            ("sharepoint_resolve_url", SHARE.replace("u!", "x"), False),
            ("sharepoint_resolve_url", "/shares", False),
            ("sharepoint_resolve_url", "/sites", False),
            ("sharepoint_read_file", SHARE, False),
        ],
    )
    def test_a_read_glob_allows_one_tool_one_path(
        self, tool: str, path: str, allowed: bool
    ) -> None:
        assert (refusal(tool, "GET", path) is None) == allowed

    def test_a_read_glob_allows_a_get_and_nothing_else(self) -> None:
        assert "outside" in str(refusal("sharepoint_search_sites", "POST", "/sites"))
        assert "outside" in str(refusal("sharepoint_resolve_url", "DELETE", SHARE))

    def test_a_read_of_the_search_index_is_allowed(self) -> None:
        assert refusal("sharepoint_search_files", "POST", "/search/query") is None
        assert refusal("sharepoint_rename_item", "POST", "/search/query") is not None


def scrubbed(path: str, answer: object, *, method: str = "GET", status: int = 200) -> Fixture:
    asked: Json = {
        "method": method,
        "host": GRAPH_HOST,
        "path": path,
        "query": {},
        "headers": {},
        "json": None,
    }
    body = json.dumps(answer).encode() if answer is not None else b""
    headers = (("content-type", "application/json"),) if body else ()
    hop = Hop(asked, f"{GRAPH}{path}", False, status, headers, body)
    identities = Identities(frozenset({stand_in.USER_ID, stand_in.DRIVE_ID, *stand_in.UPNS}), "t")
    personas = {
        upn.casefold(): key for upn, key in zip(stand_in.UPNS, ("mia", "anna", "tom"), strict=True)
    }
    recording = Recording(
        "synthetic",
        "rec-synthetic",
        "stand-in",
        datetime.now(UTC),
        (hop,),
        identities,
        personas,
        frozenset(),
    )
    fixture = scrub(recording)
    assert lint_files(files_of(fixture), identities.values) == []
    return fixture


def kept(fixture: Fixture) -> Json:
    return mapping(cast("object", json.loads(fixture.bodies["rec-synthetic.01.json"])))


class TestScrubShapes:
    def test_the_profile_keeps_its_fields_with_synthetic_addresses(self) -> None:
        answer = {
            "id": stand_in.USER_ID,
            "displayName": "Mia Keller",
            "givenName": "Mia",
            "surname": "Keller",
            "mail": stand_in.UPN,
            "userPrincipalName": stand_in.UPN,
            "jobTitle": "Project Lead",
            "officeLocation": None,
            "businessPhones": ["+41 44 000 00 00"],
            "mobilePhone": None,
            "preferredLanguage": "en-US",
        }
        fixture = scrubbed("/v1.0/me", answer)
        found = kept(fixture)
        assert fixture.dropped == {}
        assert found["mail"] == found["userPrincipalName"] == "mia@example.test"
        assert (found["givenName"], found["jobTitle"]) == ("Mia", "Project Lead")
        assert found["businessPhones"] == ["synthetic text 01"]
        assert found["preferredLanguage"] == "en-US"

    def test_the_drive_list_keeps_the_owner(self) -> None:
        drive = {
            "id": stand_in.DRIVE_ID,
            "name": "OneDrive",
            "driveType": "business",
            "description": "",
            "webUrl": f"https://{stand_in.MY_HOST}{stand_in.ONEDRIVE_PATH}/Documents",
            "owner": {
                "user": {"displayName": "Mia Keller", "email": stand_in.UPN, "id": stand_in.USER_ID}
            },
        }
        fixture = scrubbed("/v1.0/me/drives", {"value": [drive]})
        found = mapping(items(kept(fixture)["value"])[0])
        assert fixture.dropped == {}
        assert mapping(mapping(found["owner"])["user"])["email"] == "mia@example.test"
        assert (
            found["webUrl"]
            == "https://contoso-my.sharepoint.com/personal/mia_example_test/Documents"
        )

    def test_the_drive_root_keeps_its_root_facet(self) -> None:
        answer = {
            "id": ITEM,
            "name": "root",
            "root": {},
            "folder": {"childCount": 3},
            "parentReference": {"driveId": stand_in.DRIVE_ID, "driveType": "business"},
        }
        fixture = scrubbed(f"/v1.0{PATH}/root", answer)
        found = kept(fixture)
        assert found["root"] == {}
        assert mapping(found["folder"])["childCount"] == 3
        assert fixture.dropped == {}

    def test_a_sharing_link_keeps_its_kind_and_audience(self) -> None:
        answer = {
            "id": "aTkGcmlkLW9wYXF1ZS1wZXJtaXNzaW9u",
            "roles": ["read"],
            "hasPassword": False,
            "link": {"type": "view", "scope": "organization", "webUrl": f"{LINK}/EhAbCdEfGhIjKlMn"},
        }
        fixture = scrubbed(f"/v1.0{PATH}/{ITEM}/createLink", answer, method="POST", status=201)
        link = mapping(kept(fixture)["link"])
        assert (link["type"], link["scope"]) == ("view", "organization")
        assert str(link["webUrl"]).startswith("https://contoso-my.sharepoint.com/")
        assert "link" not in fixture.dropped
        assert "hasPassword" in fixture.dropped

    def test_a_created_folder_keeps_its_folder_facet_and_parent(self) -> None:
        answer = {
            "id": TARGET,
            "name": "seed-v1 case-sharepoint_create_folder-seed-folder",
            "folder": {"childCount": 0},
            "parentReference": {"driveId": stand_in.DRIVE_ID, "id": ITEM},
        }
        fixture = scrubbed(f"/v1.0{PATH}/{ITEM}/children", answer, method="POST", status=201)
        found = kept(fixture)
        assert mapping(found["folder"])["childCount"] == 0
        assert mapping(found["parentReference"])["id"] != ITEM
        assert fixture.dropped == {}

    def test_an_empty_answer_keeps_no_body(self) -> None:
        fixture = scrubbed(f"/v1.0{PATH}/{ITEM}", None, method="DELETE", status=204)
        assert fixture.interactions[0]["status"] == 204
        assert "body" not in fixture.interactions[0]
