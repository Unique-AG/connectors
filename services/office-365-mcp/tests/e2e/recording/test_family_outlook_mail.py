import json
import re
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime
from typing import cast

import httpx
import jsonschema
import pytest
from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport

from office_365_mcp.tools import TOOL_NAMES
from tests.e2e.recording import stand_in
from tests.e2e.recording.cases import case_entries
from tests.e2e.recording.families import load
from tests.e2e.recording.guard import GRAPH_HOST, SEED_CASE, Guard
from tests.e2e.recording.lint import lint_files
from tests.e2e.recording.record import check, guard_for, resolve
from tests.e2e.recording.runbook import plan_runs
from tests.e2e.recording.scrub import (
    SEED,
    Hop,
    Identities,
    Recording,
    files_of,
    load_corpus,
    scrub,
)
from tests.e2e.test_scenarios import Json, build_server, items, mapping

MAIL_TOOLS = frozenset(
    {
        "outlook_browse_folders",
        "outlook_copy_mail",
        "outlook_create_category",
        "outlook_create_folder",
        "outlook_create_mail_rule",
        "outlook_delete_folder",
        "outlook_delete_mail_rule",
        "outlook_disable_mail_rule",
        "outlook_draft_mail",
        "outlook_draft_reply",
        "outlook_draft_reply_all",
        "outlook_get_mail_tips",
        "outlook_get_mailbox_settings",
        "outlook_list_attachments",
        "outlook_list_categories",
        "outlook_list_focused_overrides",
        "outlook_list_mail",
        "outlook_mark_mail",
        "outlook_move_mail",
        "outlook_read_attachment",
        "outlook_read_mail",
        "outlook_read_thread",
        "outlook_rename_folder",
        "outlook_search_mail",
        "outlook_send_draft",
        "outlook_set_automatic_reply",
        "outlook_set_focused_override",
        "outlook_update_draft",
        "outlook_update_mail_rule",
    }
)
CORPUS_FILES = ("mail.yaml", "events.yaml", "outlook-calendar.yaml")
NAMING_ARGUMENT = {
    "outlook_create_folder": "name",
    "outlook_create_category": "name",
    "outlook_create_mail_rule": "display_name",
    "outlook_draft_mail": "subject",
}
TAGGED_CATEGORIES = frozenset({"outlook_draft_reply", "outlook_draft_reply_all"})
GRAPH = f"https://{GRAPH_HOST}/v1.0"
SELECTOR = re.compile(r"\[(\d+|\*)\]|\.?([^.\[]+)")
DAY = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)


def last_tool(entry: Json) -> str:
    return str(mapping(items(entry["chain"])[-1])["tool"])


def mail_cases() -> dict[str, Json]:
    return {name: entry for name, entry in case_entries() if last_tool(entry) in MAIL_TOOLS}


def steps_of(entry: Json) -> list[Json]:
    return [mapping(step) for step in items(entry["chain"])]


class TestTheFamilyPlugIn:
    def test_every_tool_has_a_case_or_a_reason(self) -> None:
        covered = {last_tool(entry) for entry in mail_cases().values()}
        assert covered == MAIL_TOOLS

    def test_the_plug_in_claims_each_tool_with_a_case_once(self) -> None:
        merged = load()
        claimed = merged.read_tools | set(merged.write_tools)
        assert claimed >= MAIL_TOOLS
        assert set(TOOL_NAMES) >= MAIL_TOOLS

    @pytest.mark.parametrize("case", sorted(mail_cases()))
    def test_a_case_passes_the_guard_plan(self, case: str) -> None:
        plan = resolve(case)
        assert check(plan, guard_for(stand_in.UPNS, plan, True, 40)) == []

    @pytest.mark.parametrize("case", sorted(mail_cases()))
    def test_a_case_names_what_it_creates_with_its_own_id(self, case: str) -> None:
        tag = f"{SEED_CASE}{case}"
        for step in steps_of(mail_cases()[case]):
            args, tool = mapping(step.get("args", {})), str(step["tool"])
            if tool in NAMING_ARGUMENT:
                assert tag in str(args[NAMING_ARGUMENT[tool]])
            if tool in TAGGED_CATEGORIES:
                assert any(tag in str(one) for one in items(args["categories"]))

    def test_the_search_case_asks_for_words_that_only_plain_mail_holds(self) -> None:
        step = steps_of(mail_cases()["outlook_search_mail-budget"])[0]
        query = str(mapping(step["args"])["query"]).casefold()
        read = {name: (SEED / "corpus" / name).read_text().casefold() for name in CORPUS_FILES}
        assert query in read["mail.yaml"]
        assert query not in read["events.yaml"] + read["outlook-calendar.yaml"]

    def test_only_the_example_case_destroys_a_seed_item(self) -> None:
        destructive = {name for name, entry in mail_cases().items() if entry.get("destructive")}
        assert destructive == {"outlook_move_mail-archive"}

    def test_the_send_case_is_the_only_external_one(self) -> None:
        external = {name for name, entry in mail_cases().items() if entry.get("external")}
        assert external == {"outlook_send_draft-persona"}
        assert load().external >= {"outlook_send_draft"}

    def test_the_attachment_case_needs_nothing_from_a_person(self) -> None:
        plan = resolve("outlook_read_attachment-first")
        [run] = plan_runs([plan], frozenset(), {}, False)
        assert run.status == "run"
        assert "attachment-bytes" not in load().needs


def unwrapped(schema: Json) -> Json:
    options = [mapping(one) for one in items(schema.get("anyOf", []))]
    return next((one for one in options if one.get("type") != "null"), schema)


def reaches(schema: Json, selector: str) -> bool:
    for index, name in cast("list[tuple[str, str]]", SELECTOR.findall(selector)):
        schema = unwrapped(schema)
        if index:
            if "items" not in schema:
                return False
            schema = mapping(schema["items"])
        else:
            properties = mapping(schema.get("properties", {}))
            if name not in properties:
                return False
            schema = mapping(properties[name])
    return True


def references(value: object) -> Iterator[str]:
    if isinstance(value, str) and value.startswith("$"):
        yield value
    elif isinstance(value, list):
        for one in cast("list[object]", value):
            yield from references(one)


class TestTheChains:
    async def test_each_step_fits_its_tool_and_binds_a_field_that_exists(self) -> None:
        async with Client(FastMCPTransport(build_server()), mode="legacy") as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
        problems: list[str] = []
        for name, entry in sorted(mail_cases().items()):
            steps = steps_of(entry)
            for number, step in enumerate(steps, 1):
                tool = tools[str(step["tool"])]
                given = {**mapping(step.get("args", {})), **mapping(step.get("bind", {}))}
                schema = mapping(cast("object", tool.input_schema))
                properties = mapping(schema["properties"])
                required = set(cast("list[str]", schema.get("required", [])))
                where = f"{name} step {number}"
                problems += [
                    f"{where}: unknown argument {key}" for key in given - properties.keys()
                ]
                problems += [f"{where}: no {key}" for key in sorted(required - given.keys())]
                for key, value in mapping(step.get("args", {})).items():
                    try:
                        jsonschema.validate(value, dict(mapping(properties[key])))
                    except jsonschema.ValidationError as invalid:
                        problems.append(f"{where}: {key} {invalid.message}")
                for key, value in mapping(step.get("bind", {})).items():
                    for reference in references(value):
                        root, _, selector = reference[1:].partition(".")
                        earlier = number - 1 if root == "prev" else int(root)
                        if not 1 <= earlier < number:
                            problems.append(f"{where}: {key} binds {reference}, a later step")
                            continue
                        source = tools[str(steps[earlier - 1]["tool"])]
                        output = mapping(cast("object", source.output_schema))
                        if not reaches(output, selector):
                            problems.append(f"{where}: {key} binds {reference}, which is no field")
        assert problems == []


def guard(created: frozenset[str] | None = None) -> Guard:
    return Guard(stand_in.UPN, frozenset(stand_in.UPNS), True, created=set(created or ()))


def sent(method: str, path: str, body: object = None) -> httpx.Request:
    content = "" if body is None else json.dumps(body)
    return httpx.Request(method, f"{GRAPH}{path}", content=content)


NEW = "AAMkNEWITEM"
TRASH = "AAMkTRASHFOLDER"
OVERRIDE = f"/me/inferenceClassification/overrides/{NEW}"
RULE = f"/me/mailFolders/inbox/messageRules/{NEW}"
ALLOWED: Sequence[tuple[str, str, str, object]] = (
    ("outlook_create_folder", "POST", "/me/mailFolders", {"displayName": "seed-v1 case-x"}),
    ("outlook_create_folder", "POST", f"/me/mailFolders/{NEW}/childFolders", {"displayName": "x"}),
    ("outlook_rename_folder", "PATCH", f"/me/mailFolders/{NEW}", {"displayName": "x"}),
    ("outlook_copy_mail", "POST", f"/me/messages/{NEW}/copy", {"destinationId": NEW}),
    ("outlook_move_mail", "POST", f"/me/messages/{NEW}/move", {"destinationId": "archive"}),
    ("outlook_create_category", "POST", "/me/outlook/masterCategories", {"displayName": "x"}),
    ("outlook_create_mail_rule", "POST", "/me/mailFolders/inbox/messageRules", {"sequence": 1}),
    ("outlook_update_mail_rule", "PATCH", RULE, {"displayName": "x"}),
    ("outlook_disable_mail_rule", "PATCH", RULE, {"isEnabled": False}),
    ("outlook_delete_mail_rule", "DELETE", RULE, None),
    ("outlook_draft_mail", "POST", "/me/messages", {"subject": "x"}),
    ("outlook_draft_reply", "POST", f"/me/messages/{NEW}/createReply", {}),
    ("outlook_draft_reply", "POST", f"/me/messages/{NEW}/createForward", {}),
    ("outlook_draft_reply", "PATCH", f"/me/messages/{NEW}", {"categories": ["x"]}),
    ("outlook_draft_reply_all", "POST", f"/me/messages/{NEW}/createReplyAll", {}),
    ("outlook_mark_mail", "PATCH", f"/me/messages/{NEW}", {"flag": {"flagStatus": "flagged"}}),
    ("outlook_update_draft", "PATCH", f"/me/messages/{NEW}", {"subject": "x"}),
    ("outlook_send_draft", "POST", f"/me/messages/{NEW}/send", None),
    ("outlook_set_automatic_reply", "PATCH", "/me/mailboxSettings", {"x": {"status": "disabled"}}),
    ("outlook_set_focused_override", "POST", "/me/inferenceClassification/overrides", {}),
    ("outlook_set_focused_override", "PATCH", OVERRIDE, {"classifyAs": "other"}),
    ("outlook_get_mail_tips", "POST", "/me/getMailTips", {"EmailAddresses": []}),
    ("outlook_search_mail", "POST", "/me/translateExchangeIds", {"inputIds": []}),
)
REFUSED: Sequence[tuple[str, str, str, object]] = (
    ("outlook_draft_mail", "DELETE", f"/me/messages/{NEW}", None),
    ("outlook_draft_mail", "POST", "/me/sendMail", {}),
    ("outlook_draft_mail", "PATCH", f"/me/messages/{NEW}", {}),
    ("outlook_move_mail", "POST", f"/me/messages/{NEW}/permanentDelete", None),
    ("outlook_move_mail", "POST", f"/me/messages/{NEW}/move", {"destinationId": "AAMkOTHER"}),
    ("outlook_send_draft", "POST", "/me/messages/AAMkOTHER/send", None),
    ("outlook_send_draft", "POST", f"/me/messages/{NEW}/forward", {}),
    ("outlook_create_folder", "PATCH", f"/me/mailFolders/{NEW}", {}),
    ("outlook_delete_mail_rule", "DELETE", "/me/mailFolders/inbox/messageRules/AAMkOTHER", None),
    ("outlook_delete_mail_rule", "DELETE", f"/me/mailFolders/drafts/messageRules/{NEW}", None),
    ("outlook_set_automatic_reply", "PATCH", "/me/mailboxSettings", {"x": {"status": "scheduled"}}),
    (
        "outlook_set_automatic_reply",
        "PATCH",
        "/me/mailboxSettings",
        {"x": {"status": "alwaysEnabled"}},
    ),
    ("outlook_set_focused_override", "DELETE", OVERRIDE, None),
    ("outlook_get_mailbox_settings", "PATCH", "/me/mailboxSettings", {}),
    ("outlook_browse_folders", "POST", "/me/mailFolders", {}),
    ("outlook_list_mail", "POST", "/me/messages", {}),
    ("outlook_get_mail_tips", "POST", "/me/sendMail", {}),
)


class TestTheGuardRules:
    @pytest.mark.parametrize(("tool", "method", "path", "body"), ALLOWED)
    def test_a_path_of_the_tool_is_allowed(
        self, tool: str, method: str, path: str, body: object
    ) -> None:
        assert guard(frozenset({NEW})).refuses_request(sent(method, path, body), tool) is None

    @pytest.mark.parametrize(("tool", "method", "path", "body"), REFUSED)
    def test_any_other_path_or_target_is_refused(
        self, tool: str, method: str, path: str, body: object
    ) -> None:
        assert guard(frozenset({NEW})).refuses_request(sent(method, path, body), tool) is not None

    def test_a_draft_to_an_outside_address_is_refused(self) -> None:
        body = {"toRecipients": [{"emailAddress": {"address": "anna@outside.example"}}]}
        refusal = guard().refuses_request(sent("POST", "/me/messages", body), "outlook_draft_mail")
        assert refusal is not None
        assert "that is not a test user" in refusal

    def test_a_rule_that_moves_mail_into_an_unknown_folder_is_refused(self) -> None:
        body = {"actions": {"moveToFolder": "AAMkOTHER"}}
        made = guard(frozenset({"AAMkFOLDER"}))
        refusal = made.refuses_request(
            sent("POST", "/me/mailFolders/inbox/messageRules", body), "outlook_create_mail_rule"
        )
        known = {"actions": {"moveToFolder": "AAMkFOLDER"}}
        accepted = made.refuses_request(
            sent("POST", "/me/mailFolders/inbox/messageRules", known), "outlook_create_mail_rule"
        )
        assert refusal is not None
        assert accepted is None

    def test_a_folder_moves_to_the_deleted_items_id_that_a_read_answered(self) -> None:
        made = guard(frozenset({NEW}))
        move = sent("POST", f"/me/mailFolders/{NEW}/move", {"destinationId": TRASH})
        assert "did not read as seed" in str(made.refuses_request(move, "outlook_delete_folder"))
        made.saw(sent("GET", "/me/mailFolders/deleteditems"), 200, None, {"id": TRASH})
        assert made.refuses_request(move, "outlook_delete_folder") is None
        stranger = sent("POST", f"/me/mailFolders/{NEW}/move", {"destinationId": "AAMkOTHER"})
        assert made.refuses_request(stranger, "outlook_delete_folder") is not None

    @pytest.mark.parametrize(
        ("method", "path", "status"),
        [
            ("GET", f"/me/mailFolders/{NEW}", 200),
            ("GET", "/me/mailFolders/deleteditems/childFolders", 200),
            ("GET", "/me/mailFolders/deleteditems", 404),
            ("GET", "/me/mailFolders/notes", 200),
            ("POST", "/me/mailFolders/deleteditems", 200),
        ],
    )
    def test_only_a_read_of_a_well_known_folder_makes_its_id_known(
        self, method: str, path: str, status: int
    ) -> None:
        made = guard(frozenset({NEW}))
        made.saw(sent(method, path), status, None, {"id": TRASH})
        move = sent("POST", f"/me/mailFolders/{NEW}/move", {"destinationId": TRASH})
        assert "did not read as seed" in str(made.refuses_request(move, "outlook_delete_folder"))


def ids(count: int) -> list[str]:
    return [stand_in.exchange_id(b"\x00\x03\x24\x00", n) for n in range(count)]


ID = ids(12)
RULE_NAME = f"{SEED_CASE}outlook_create_mail_rule-basic"
CATEGORY_NAME = f"{SEED_CASE}outlook_create_category-basic"
WINDOW = {"dateTime": "2026-10-29T08:00:00.0000000", "timeZone": "UTC"}
SHAPES: Mapping[str, object] = {
    "folders": {
        "@odata.context": "https://graph.microsoft.com/v1.0/$metadata#folders",
        "value": [
            {
                "id": ID[0],
                "displayName": "Inbox",
                "parentFolderId": ID[1],
                "childFolderCount": 0,
                "unreadItemCount": 3,
                "totalItemCount": 29,
                "isHidden": False,
            },
            {"id": ID[2], "displayName": "seed-v1 Projects", "isHidden": True},
        ],
    },
    "attachments": {
        "value": [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "id": ID[3],
                "name": "q3-numbers.csv",
                "contentType": "text/csv",
                "size": 62,
                "isInline": False,
                "lastModifiedDateTime": "2026-10-28T09:00:00Z",
            }
        ]
    },
    "rules": {
        "value": [
            {
                "id": ID[4],
                "displayName": RULE_NAME,
                "sequence": 10,
                "isEnabled": True,
                "isReadOnly": False,
                "hasError": False,
                "conditions": {"subjectContains": [RULE_NAME], "senderContains": ["Anna Meier"]},
                "exceptions": {},
                "actions": {
                    "markAsRead": True,
                    "assignCategories": ["Website"],
                    "stopProcessingRules": False,
                    "moveToFolder": ID[2],
                },
            }
        ]
    },
    "categories": {
        "value": [
            {"id": ID[5], "displayName": "Website", "color": "preset3"},
            {"id": ID[6], "displayName": CATEGORY_NAME, "color": "none"},
        ]
    },
    "automatic reply": {
        "@odata.context": "https://graph.microsoft.com/v1.0/$metadata#settings",
        "automaticRepliesSetting": {
            "status": "disabled",
            "externalAudience": "none",
            "internalReplyMessage": "",
            "externalReplyMessage": "",
            "scheduledStartDateTime": WINDOW,
            "scheduledEndDateTime": WINDOW,
        },
    },
    "overrides": {
        "value": [
            {
                "id": ID[7],
                "classifyAs": "focused",
                "senderEmailAddress": {"name": "Anna Meier", "address": stand_in.UPNS[1]},
            }
        ]
    },
    "mail tips": {
        "value": [
            {
                "emailAddress": {"name": "", "address": stand_in.UPNS[1]},
                "automaticReplies": {
                    "message": "",
                    "messageLanguage": {"locale": "en-US", "displayName": ""},
                    "scheduledStartTime": WINDOW,
                    "scheduledEndTime": WINDOW,
                },
                "customMailTip": "",
                "deliveryRestricted": False,
                "isModerated": False,
                "mailboxFull": False,
                "externalMemberCount": 0,
                "totalMemberCount": 0,
                "maxMessageSize": 37748736,
                "recipientScope": "internal",
                "recipientSuggestions": list[object](),
            }
        ]
    },
    "id translation": {"value": [{"sourceId": ID[8], "targetId": ID[9]}]},
    "message with a unique body": {
        "id": ID[10],
        "subject": "Q3 budget: travel costs",
        "categories": ["seed-v1", "Finance", "Offsite"],
        "uniqueBody": {
            "contentType": "text",
            "content": "Travel costs for the offsite go to cost center 4100.",
        },
    },
}
TRANSLATE = {"inputIds": ID[8:9], "sourceIdType": "restId", "targetIdType": "restImmutableEntryId"}


def keys_of(value: object) -> set[str]:
    if isinstance(value, list):
        return {key for one in cast("list[object]", value) for key in keys_of(one)}
    if isinstance(value, Mapping):
        found = cast("Json", value)
        return set(found) | {key for one in found.values() for key in keys_of(one)}
    return set()


def recorded(body: object, asked: object = None) -> Recording:
    hop = Hop(
        {
            "method": "POST" if asked is not None else "GET",
            "host": GRAPH_HOST,
            "path": "/v1.0/me/x",
            "query": {},
            "headers": {},
            "json": asked,
        },
        f"{GRAPH}/me/x",
        True,
        200,
        (("content-type", "application/json"),),
        json.dumps(body).encode(),
    )
    personas = {stand_in.UPNS[p.index - 1].casefold(): p.key for p in load_corpus().personas}
    identities = Identities(frozenset(stand_in.UPNS), "token")
    literals = frozenset({RULE_NAME, CATEGORY_NAME})
    return Recording("shape", "rec-shape", "stand-in", DAY, (hop,), identities, personas, literals)


class TestTheSchema:
    @pytest.mark.parametrize("shape", SHAPES)
    def test_a_shape_of_the_family_keeps_its_keys_and_lints_clean(self, shape: str) -> None:
        body = SHAPES[shape]
        made = recorded(body, TRANSLATE if shape == "id translation" else None)
        fixture = scrub(made)
        text = fixture.bodies["rec-shape.01.json"].decode()
        kept = keys_of(cast("object", json.loads(text)))
        assert keys_of(body) - {"@odata.context"} <= kept
        assert set(fixture.dropped) <= {"@odata.context"}
        assert "synthetic text" not in text
        assert lint_files(files_of(fixture), made.identities.everything()) == []

    def test_a_mapped_id_translation_matches_the_asked_ids(self) -> None:
        fixture = scrub(recorded(SHAPES["id translation"], TRANSLATE))
        asked = mapping(fixture.interactions[0]["json"])
        answer = mapping(
            items(
                mapping(cast("object", json.loads(fixture.bodies["rec-shape.01.json"])))["value"]
            )[0]
        )
        assert asked["inputIds"] == [answer["sourceId"]]
        assert asked["inputIds"] != TRANSLATE["inputIds"]

    def test_a_free_text_of_a_rule_that_is_not_corpus_text_is_replaced(self) -> None:
        body = {"value": [{"id": ID[4], "displayName": "Invoices of Brightway"}]}
        fixture = scrub(recorded(body))
        assert "synthetic text" in fixture.bodies["rec-shape.01.json"].decode()
