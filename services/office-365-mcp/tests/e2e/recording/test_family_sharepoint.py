import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import httpx
import pytest
import yaml

from tests.e2e.recording import cases as cases_module
from tests.e2e.recording import stand_in
from tests.e2e.recording.conftest import body_of, record_on
from tests.e2e.recording.families import load
from tests.e2e.recording.guard import GRAPH_HOST, READ_TOOLS, WRITE_TOOLS, Guard
from tests.e2e.recording.lint import lint_files
from tests.e2e.recording.record import describe, guard_for, resolve
from tests.e2e.recording.scrub import (
    Fixture,
    Hop,
    Identities,
    Recording,
    files_of,
    load_corpus,
    scrub,
)
from tests.e2e.test_scenarios import Json, expected_error, items, mapping

CASES = mapping(
    cast(
        "object",
        yaml.safe_load((Path(cases_module.__file__).parent / "sharepoint.yaml").read_text()),
    )
)
SEED = Path(__file__).resolve().parents[3] / "scripts" / "dogfood" / "seed" / "corpus"
TREE = mapping(cast("object", yaml.safe_load((SEED / "files-tree.yaml").read_text())))
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
OLD_EXTERNAL = {"sharepoint_create_share_link-plan", "sharepoint_invite-anna"}
NEW_EXTERNAL = {
    "sharepoint_copy_item-cross-drive",
    "sharepoint_invite-write-notify",
    "sharepoint_invite-note-500",
    "sharepoint_create_share_link-organization-edit",
    "sharepoint_resolve_url-sharing-link",
}
INDEX_NEEDS = {"sharepoint-seed-files", "sharepoint-tree", "sharepoint-big-files"}
TEAM_DRIVE = "b!TEAMLIBRARYAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
NEW_FILE = f"{PATH}/{ITEM}:/seed-v1 case-x.txt:/content"
SHARE = "/shares/u!aHR0cHM6Ly9jb250b3NvLXRlc3QvYQ/driveItem"
SITE = f"contoso.sharepoint.com,{stand_in.SITE_ID},{stand_in.LIST_ID}"


OLD_CASES = {
    c
    for c in (
        "get_me-profile sharepoint_list_drives-mine sharepoint_browse_folder-root "
        + "sharepoint_browse_folder-seed-folder sharepoint_search_files-plan "
        + "sharepoint_read_file-docx sharepoint_rename_item-notes sharepoint_delete_item-brochure "
        + "sharepoint_create_folder-seed-folder sharepoint_copy_item-brochure "
        + "sharepoint_move_item-budget sharepoint_create_share_link-plan "
        + "sharepoint_create_text_file-seed-folder sharepoint_invite-anna "
        + "sharepoint_resolve_url-plan sharepoint_search_sites-all"
    ).split()
}


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
            assert plan.persona == 1
            if case in OLD_CASES:
                assert plan.destructive == wrote
                assert plan.reseed == (("files",) if wrote else ())
                assert plan.external == (case in OLD_EXTERNAL)
            else:
                assert (plan.destructive, plan.reseed) == (False, ())
                assert plan.external == (case in NEW_EXTERNAL)

    def test_a_case_that_needs_the_index_waits_for_the_seed_files(self) -> None:
        searching = [c for c in CASES if "sharepoint_search_files" in json.dumps(CASES[c])]
        assert searching
        assert all(set(resolve(c).needs) & INDEX_NEEDS for c in searching)
        assert {"sharepoint-seed-files"} <= set(load().probes) & set(load().needs)
        for case in CASES:
            assert set(resolve(case).needs) <= set(load().probes) & set(load().needs)

    def test_a_case_names_no_address(self) -> None:
        assert "@" not in json.dumps(CASES)

    def test_a_case_names_what_it_creates_with_its_own_case_tag(self) -> None:
        naming = CREATING | {"sharepoint_rename_item"}
        arguments = [
            (case, mapping(mapping(step).get("args", {})))
            for case in CASES
            for step in items(mapping(CASES[case])["chain"])
            if mapping(step)["tool"] in naming
        ]
        names = [(case, str(given["name"])) for case, given in arguments if "name" in given]
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
            ("sharepoint_list_lists", "/sites/contoso.sharepoint.com", True),
            ("sharepoint_list_lists", "/sites/contoso.sharepoint.com:/sites/Finance", True),
            ("sharepoint_list_lists", "/sites/contoso.sharepoint.com:/teams/Sales", True),
            ("sharepoint_list_lists", f"/sites/{SITE}/lists", True),
            ("sharepoint_list_lists", "/sites/contoso.sharepoint.com:/sites/Finance/Sub", False),
            ("sharepoint_list_lists", "/sites/contoso.example:/sites/Finance", False),
            ("sharepoint_list_lists", f"/sites/{SITE}/drives", False),
            ("sharepoint_list_lists", f"/sites/{SITE}/lists/L1/items", False),
            ("sharepoint_get_list", f"/sites/{SITE}/lists/L1/columns", True),
            ("sharepoint_get_list", f"/sites/{SITE}/lists/L1/items", False),
            ("sharepoint_get_list", "/sites/contoso.sharepoint.com/lists/L1/columns", False),
            ("sharepoint_list_items", f"/sites/{SITE}/lists/L1/columns", True),
            ("sharepoint_list_items", f"/sites/{SITE}/lists/L1/items", True),
            ("sharepoint_list_items", f"/sites/{SITE}/lists/L1/items/7", False),
            ("sharepoint_list_items", f"/sites/{SITE}/lists/L1/items/7/fields", False),
            ("sharepoint_list_items", "/sites", False),
            ("sharepoint_create_list_item", f"/sites/{SITE}/lists/L1", True),
            ("sharepoint_update_list_item", f"/sites/{SITE}/lists/L1", True),
            ("sharepoint_delete_list_item", f"/sites/{SITE}/lists/L1", True),
            ("sharepoint_get_list", f"/sites/{SITE}/lists/L1", False),
            ("sharepoint_create_list_item", "/sites/contoso.sharepoint.com/lists/L1", False),
        ],
    )
    def test_a_read_glob_allows_one_tool_one_path(
        self, tool: str, path: str, allowed: bool
    ) -> None:
        assert (refusal(tool, "GET", path) is None) == allowed

    def test_a_read_glob_allows_a_get_and_nothing_else(self) -> None:
        assert "outside" in str(refusal("sharepoint_search_sites", "POST", "/sites"))
        assert "outside" in str(refusal("sharepoint_resolve_url", "DELETE", SHARE))

    @pytest.mark.parametrize(
        ("tool", "method", "suffix"),
        [
            ("sharepoint_create_list_item", "POST", "items"),
            ("sharepoint_update_list_item", "PATCH", "items/7/fields"),
            ("sharepoint_delete_list_item", "DELETE", "items/7"),
        ],
    )
    def test_a_list_item_write_checks_the_list_and_the_row_but_not_the_site(
        self, tool: str, method: str, suffix: str
    ) -> None:
        shown = f"/sites/{SITE}/lists/L1/{suffix}"
        made = guard()
        request = httpx.Request(method, f"{GRAPH}{shown}", content=json.dumps({}))
        assert "did not read as seed data" in str(made.refuses_request(request, tool))
        listed = {
            "value": [
                {"id": "L1", "displayName": "seed-v1 Tasks"},
                {"id": "L2", "displayName": "seed-v1 Issues"},
            ]
        }
        read = {"value": [{"id": "7", "fields": {"Title": "seed-v1 Close books"}}]}
        for path, body in (
            (f"/sites/{SITE}/lists", listed),
            (f"/sites/{SITE}/lists/L1/items", read),
        ):
            made.saw(httpx.Request("GET", f"{GRAPH}{path}"), 200, None, body)
        assert made.refuses_request(request, tool) is None
        other = httpx.Request(method, f"{GRAPH}/sites/{SITE}/lists/L2/{suffix}", content="{}")
        refused = made.refuses_request(other, tool)
        assert ("did not read as seed data" in str(refused)) == ("7" in suffix)

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
    return mapping(cast("object", json.loads(body_of(fixture, "rec-synthetic.01"))))


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


def library(suffix: str) -> str:
    return f"/drives/{TEAM_DRIVE}/items/{ITEM}{suffix}"


class TestTeamLibraryAndSharing:
    @pytest.mark.parametrize(
        ("tool", "suffix", "allowed"),
        [
            ("sharepoint_browse_folder", "/children", True),
            ("sharepoint_browse_folder", "", False),
            ("sharepoint_browse_folder", "/content", False),
            ("sharepoint_browse_folder", "/permissions", False),
            ("sharepoint_read_file", "", False),
            ("sharepoint_read_file", "/content", False),
            ("sharepoint_create_folder", "", True),
            ("sharepoint_create_folder", "/children", False),
            ("sharepoint_copy_item", "", True),
            ("sharepoint_copy_item", "/content", False),
            ("sharepoint_search_files", "/children", False),
            ("sharepoint_resolve_url", "", False),
            ("sharepoint_rename_item", "", False),
            ("sharepoint_delete_item", "", False),
            ("sharepoint_invite", "", False),
        ],
    )
    def test_another_drive_is_open_to_a_named_tool_on_a_named_path_for_reading_only(
        self, tool: str, suffix: str, allowed: bool
    ) -> None:
        assert (refusal(tool, "GET", library(suffix)) is None) == allowed
        assert "outside" in str(refusal("sharepoint_browse_folder", "DELETE", library("/children")))

    def test_a_folder_in_the_team_library_needs_a_parent_that_the_run_read_as_seed_data(
        self,
    ) -> None:
        body = json.dumps({"name": "seed-v1 case-x", "folder": {}})
        unseen = httpx.Request(
            "POST", f"{GRAPH}/drives/{TEAM_DRIVE}/items/01OTHER/children", content=body
        )
        seen = httpx.Request("POST", f"{GRAPH}{library('/children')}", content=body)
        assert "did not read as seed" in str(
            guard().refuses_request(unseen, "sharepoint_create_folder")
        )
        assert guard().refuses_request(seen, "sharepoint_create_folder") is None
        assert "outside" in str(guard().refuses_request(seen, "sharepoint_rename_item"))

    def test_a_copy_into_another_drive_goes_into_a_folder_that_the_run_knows(self) -> None:
        made = guard()
        made.created.add(FOLDER)
        path = f"{GRAPH}{PATH}/{ITEM}/copy"

        def copy(folder: str) -> str | None:
            body = {"parentReference": {"driveId": TEAM_DRIVE, "id": folder}}
            return made.refuses_request(
                httpx.Request("POST", path, content=json.dumps(body)), "sharepoint_copy_item"
            )

        assert copy(FOLDER) is None
        assert "did not read as seed" in str(copy("01OTHER"))

    def test_an_invitation_may_give_write_access_with_a_notice_and_a_note_of_2000_characters(
        self,
    ) -> None:
        made = guard()
        made.created.add(FOLDER)
        body = {
            "recipients": [{"email": stand_in.UPNS[1]}],
            "roles": ["write"],
            "sendInvitation": True,
            "message": "a" * 2000,
        }
        assert refusal_of(made, FOLDER, body) is None
        leaking = body | {"message": "write to x@outside.example"}
        assert "address that is not a test user" in str(refusal_of(made, FOLDER, leaking))

    def test_a_link_for_the_organization_may_edit_and_an_anonymous_link_stays_refused(self) -> None:
        made = guard()
        made.created.add(FOLDER)
        link = f"{GRAPH}{PATH}/{FOLDER}/createLink"

        def create(scope: str) -> str | None:
            body = json.dumps({"type": "edit", "scope": scope})
            return made.refuses_request(
                httpx.Request("POST", link, content=body), "sharepoint_create_share_link"
            )

        assert create("organization") is None
        assert "no recording may do" in str(create("anonymous"))

    def test_a_text_of_one_million_characters_passes_the_guard_for_its_own_tool_only(self) -> None:
        request = httpx.Request("PUT", f"{GRAPH}{NEW_FILE}", content="a" * 1_000_000)
        assert guard().refuses_request(request, "sharepoint_create_text_file") is None
        assert "may not make here" in str(guard().refuses_request(request, "sharepoint_read_file"))

    def test_the_over_cap_case_names_the_size_text_of_the_tool_as_its_error(self) -> None:
        last = mapping(items(mapping(CASES["sharepoint_read_file-over-cap"])["chain"])[-1])
        assert expected_error(mapping(last["expect"])["tool_error"]) == "10.0"

    def test_the_note_case_sends_the_500_characters_that_graph_accepts(self) -> None:
        last = mapping(items(mapping(CASES["sharepoint_invite-note-500"])["chain"])[-1])
        assert mapping(last["bind"])["message"] == {"repeat": {"text": "a", "count": 500}}

    def test_the_probe_counts_follow_the_corpus(self) -> None:
        core = mapping(cast("object", yaml.safe_load((SEED / "files.yaml").read_text())))
        mine = [mapping(one) for one in (*items(TREE["folders"]), *items(TREE["files"]))]
        inside = sum(
            one.get("parent") == "Contracts" or one.get("folder") == "Contracts" for one in mine
        )
        top = sum(
            one.get("owner", "mia") == "mia" and "parent" not in one and "folder" not in one
            for one in mine
        )
        mia = sum(mapping(one).get("owner", "mia") == "mia" for one in items(core["files"]))
        assert load().probes["sharepoint-tree"][2] == inside
        assert load().probes["sharepoint-big-files"][2] == top + mia

    def test_the_channel_cases_pick_the_channel_that_the_seed_creates(self) -> None:
        channel = f"seed-v1 {mapping(TREE['team'])['channel']}"
        assert f"display_name={channel}]" in json.dumps(CASES)

    def test_a_name_that_a_case_selects_or_expects_is_corpus_text(self) -> None:
        text = json.dumps(CASES)
        wanted = set(re.findall(r"\[(?:name|display_name)=([^\]\"]+)\]", text))
        expected = [
            mapping(mapping(step).get("expect", {})).get("result", {})
            for case in CASES.values()
            for step in items(mapping(case)["chain"])
        ]
        for result in expected:
            for value in mapping(result).values():
                listed = cast("list[object]", value) if isinstance(value, list) else [value]
                wanted |= {one for one in listed if isinstance(one, str)}
        assert wanted > {"seed-v1 Order D.txt", "Anna Meier", "seed-v1 Team Files"}
        assert sorted(wanted - load_corpus().strings) == []


def test_the_team_library_shapes_scrub_and_pass_the_lint() -> None:
    web = "https://contoso.sharepoint.com/sites/seedteam/Shared%20Documents"
    by = {"user": {"displayName": "Mia Keller"}}
    parent = {"driveId": TEAM_DRIVE, "driveType": "documentLibrary", "id": ITEM}
    folder: Json = {
        "id": TARGET,
        "name": "seed-v1 Team Files",
        "size": 2400,
        "webUrl": f"{web}/seed-v1%20Team%20Files",
        "createdBy": by,
        "lastModifiedBy": by,
        "createdDateTime": "2026-10-29T08:00:00Z",
        "lastModifiedDateTime": "2026-10-29T08:00:00Z",
        "folder": {"childCount": 3},
        "parentReference": parent,
    }
    fixture = scrubbed(f"/v1.0{library('/children')}", {"value": [folder]})
    found = mapping(items(kept(fixture)["value"])[0])
    assert fixture.dropped == {}
    assert found["name"] == "seed-v1 Team Files"
    assert mapping(found["parentReference"])["driveType"] == "documentLibrary"
    assert mapping(found["createdBy"]) == {"user": {"displayName": "Mia Keller"}}
