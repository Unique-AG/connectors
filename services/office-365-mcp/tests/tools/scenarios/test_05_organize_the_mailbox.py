import re
from collections.abc import Mapping
from typing import cast
from urllib.parse import unquote

import httpx
import pytest
import respx

from office_365_mcp.tools import PRESETS, TOOL_NAMES
from tests.conftest import RecordedSleeps
from tests.e2e.test_scenarios import Person
from tests.graph_fixtures import response, serve
from tests.tools.scenarios.mail_support import (
    FAULTS,
    advice_for,
    answer_of,
    answers,
    call_with,
    every_time,
    invoke_as,
    marking_every_message,
    methods_asked,
    moving_every_message,
    paths_asked,
    raising,
    refusal_of,
    requests_asked,
    sent_json,
    sent_jsons,
    serve_as,
    times_asked,
    tool_description,
)
from tests.tools.scenarios.support import call

_Q3_MESSAGE = (
    "outlook:///messages/UVsTDiJFUPIYQUGJVhueFs0rwRVuSL-VXg7Qf8Gswu94PmVGQa3B8fgvapZL0C73yPLW"
)
_FOLDERS = "/me/mailFolders"
_FORWARDING = {"forward_to": ["anna@example.test"]}
_OUTCOME_UNKNOWN = "does not know if Microsoft 365 made the change"
_DELETING_TOOLS = {
    "onenote_delete_page",
    "outlook_delete_calendar",
    "outlook_delete_event",
    "outlook_delete_folder",
    "outlook_delete_mail_rule",
    "sharepoint_delete_item",
    "teams_delete_meeting",
    "teams_delete_message",
    "teams_remove_chat_member",
}
_BUSY_WRITE: dict[str, object] = {
    "status": 503,
    "response_headers": {"Retry-After": "30"},
    "body": "error.TooManyRequests.json",
}


def _rows(found: object, name: str, column: str) -> list[object]:
    return [
        row[column]
        for row in cast("list[dict[str, object]]", cast("dict[str, object]", found)[name])
    ]


def _folder(folders: object, name: str) -> dict[str, str]:
    return next(
        row
        for row in cast("list[dict[str, str]]", cast("dict[str, object]", folders)["folders"])
        if row["display_name"] == name
    )


def _folder_id(uri: str) -> str:
    return unquote(uri.removeprefix("outlook:///folders/"))


def _a_visible_folder(graph: respx.MockRouter, folder: Mapping[str, str]) -> respx.Route:
    return graph.get(f"{_FOLDERS}/{_folder_id(folder['uri'])}").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": _folder_id(folder["uri"]),
                "displayName": folder["display_name"],
                "isHidden": False,
            },
        )
    )


def _uris(listing: object) -> list[str]:
    return cast("list[str]", _rows(listing, "messages", "uri"))


def _the_rule_answer(fixture: str, method: str) -> dict[str, object]:
    return answer_of(fixture, method, "/me/mailFolders/inbox/messageRules")


def _rule_route(routes: Mapping[tuple[str, str], respx.Route], method: str) -> respx.Route:
    return next(
        route
        for (verb, path), route in routes.items()
        if verb == method and "/messageRules/" in path
    )


class TestABatchIsCheckedWholeAndReportedForEachMessage:
    async def test_it_files_a_batch_in_one_folder(self, graph: respx.MockRouter) -> None:
        _ = serve(graph, "rec-tool-outlook_list_mail-inbox")
        _ = serve(graph, "rec-tool-outlook_browse_folders-top")
        _ = moving_every_message(graph)
        listing = await call("outlook_list_mail", limit=3)
        handled = _folder(await call("outlook_browse_folders", limit=50), "seed-v1 Handled")
        _ = _a_visible_folder(graph, handled)

        moved = await call(
            "outlook_move_mail", message_refs=_uris(listing), folder_ref=handled["uri"]
        )

        assert moved["destination"] == "seed-v1 Handled"
        assert (moved["moved_count"], moved["failed_count"]) == (3, 0)
        assert _rows(moved, "messages", "uri") == _uris(listing)
        assert {body["DestinationId"] for body in sent_jsons(graph, "POST", "/move")} == {
            _folder_id(handled["uri"])
        }

    @pytest.mark.parametrize(
        ("arguments", "column", "expected"),
        [
            ({"is_read": True}, "is_read", True),
            ({"flagged": True}, "flag_status", "flagged"),
            ({"add_categories": ["Reading"]}, "categories", ["Reading"]),
        ],
        ids=["read", "flag", "category"],
    )
    async def test_it_marks_a_batch_in_one_step(
        self, graph: respx.MockRouter, arguments: dict[str, object], column: str, expected: object
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_list_mail-inbox")
        _ = marking_every_message(graph)
        listing = await call("outlook_list_mail", limit=3)

        marked = await call_with("outlook_mark_mail", {"message_refs": _uris(listing)} | arguments)

        assert (marked["changed_count"], marked["failed_count"]) == (3, 0)
        assert _rows(marked, "messages", column) == [expected] * 3

    async def test_a_flag_carries_a_start_and_a_due_date_in_the_zone_that_was_named(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_list_mail-inbox")
        _ = marking_every_message(graph)
        listing = await call("outlook_list_mail", limit=3)

        _ = await call(
            "outlook_mark_mail",
            message_refs=_uris(listing),
            flagged=True,
            flag_starts_at="2026-10-30T00:00:00",
            flag_due_at="2026-11-06T17:00:00",
            flag_time_zone="W. Europe Standard Time",
        )

        flags = [cast("dict[str, object]", body["flag"]) for body in sent_jsons(graph, "PATCH", "")]
        assert len(flags) == 3
        assert [
            (flag["startDateTime"], flag["dueDateTime"], flag["flagStatus"]) for flag in flags
        ] == [
            (
                {"dateTime": "2026-10-30T00:00:00", "timeZone": "W. Europe Standard Time"},
                {"dateTime": "2026-11-06T17:00:00", "timeZone": "W. Europe Standard Time"},
                "flagged",
            )
        ] * 3

    async def test_a_flag_with_a_due_date_and_no_time_zone_changes_no_message(
        self, graph: respx.MockRouter
    ) -> None:
        advice = await advice_for(
            "outlook_mark_mail",
            message_refs=[_Q3_MESSAGE],
            flag_starts_at="2026-10-30T00:00:00",
            flag_due_at="2026-11-06T17:00:00",
        )

        assert "If you do not know the zone, ask the user" in advice
        assert "No message was changed" in advice
        assert graph.calls.call_count == 0

    async def test_messages_that_mia_named_by_subject_are_found_again_and_filed(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_search_mail-budget")
        _ = moving_every_message(graph)
        found = await call("outlook_search_mail", query="Q3 budget review", limit=5)

        moved = await call("outlook_move_mail", message_refs=_uris(found), destination="archive")

        assert (moved["moved_count"], moved["failed_count"]) == (5, 0)

    @pytest.mark.parametrize("destination", ["deleteditems", "archive"])
    async def test_a_delete_or_an_archive_moves_the_batch_and_erases_nothing(
        self, graph: respx.MockRouter, destination: str
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_list_mail-inbox")
        _ = moving_every_message(graph)
        listing = await call("outlook_list_mail", limit=3)

        moved = await call(
            "outlook_move_mail", message_refs=_uris(listing), destination=destination
        )

        assert (moved["destination"], moved["moved_count"]) == (destination, 3)
        assert {body["DestinationId"] for body in sent_jsons(graph, "POST", "/move")} == {
            destination
        }
        assert "DELETE" not in methods_asked(graph)

    async def test_a_copy_keeps_the_original_where_it_was(self, graph: respx.MockRouter) -> None:
        _ = serve(graph, "rec-tool-outlook_copy_mail-to-folder")
        created = answer_of("rec-tool-outlook_copy_mail-to-folder", "POST", "/me/mailFolders")
        contracts = f"outlook:///folders/{created['id']}"

        copied = await call("outlook_copy_mail", message_refs=[_Q3_MESSAGE], folder_ref=contracts)

        assert (copied["copied_count"], copied["failed_count"]) == (1, 0)
        assert cast("str", _rows(copied, "messages", "new_uri")[0]) != _Q3_MESSAGE
        assert [path for path in paths_asked(graph) if path.endswith("/move")] == []

    async def test_a_change_in_a_shared_mailbox_asks_first_and_then_moves(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve_as(graph, "rec-tool-outlook_move_mail-archive", "support@example.com")
        person = Person()

        moved = await invoke_as(
            "outlook_move_mail",
            {
                "mailbox": "support@example.com",
                "message_refs": [_Q3_MESSAGE],
                "destination": "archive",
            },
            person=person,
        )

        (question,) = person.asked
        assert "support@example.com" in question
        assert moved.structured_content is not None
        assert times_asked(graph, "POST", "/move") == 1

    @pytest.mark.parametrize(
        ("approval", "told"),
        [("no", "was not confirmed"), ("unanswered", "received no answer")],
        ids=["declines", "chat-program-fails"],
    )
    async def test_a_change_in_a_shared_mailbox_is_not_made_without_a_yes(
        self, graph: respx.MockRouter, approval: str, told: str
    ) -> None:
        _ = serve_as(graph, "rec-tool-outlook_move_mail-archive", "support@example.com")

        advice = await refusal_of(
            "outlook_move_mail",
            {
                "mailbox": "support@example.com",
                "message_refs": [_Q3_MESSAGE],
                "destination": "archive",
            },
            person=Person(approval=approval),
        )

        assert told in advice
        assert times_asked(graph, "POST", "/move") == 0

    async def test_a_message_that_was_deleted_by_mistake_is_put_back_in_the_inbox(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_move_mail-restore-deleted")
        listing = await call("outlook_list_mail", folder="deleteditems", limit=25)

        moved = await call(
            "outlook_move_mail", message_refs=_uris(listing)[:1], destination="inbox"
        )

        assert (moved["destination"], moved["moved_count"]) == ("inbox", 1)
        assert sent_json(graph, "POST", "/move") == {"DestinationId": "inbox"}


class TestMiaKeepsHerFoldersAsSheNamesThem:
    async def test_a_folder_is_created_inside_another_folder(self, graph: respx.MockRouter) -> None:
        _ = serve(graph, "rec-tool-outlook_create_folder-child")
        projects = await call("outlook_create_folder", name="Projects")

        alpha = await call("outlook_create_folder", name="Alpha", parent_ref=projects["uri"])

        children = [path for path in paths_asked(graph) if path.endswith("/childFolders")]
        assert children == [
            f"/v1.0{_FOLDERS}/{_folder_id(cast('str', projects['uri']))}/childFolders"
        ]
        assert sent_jsons(graph, "POST", "/childFolders") == [{"displayName": "Alpha"}]
        assert alpha["uri"] != projects["uri"]

    async def test_a_folder_is_renamed_where_it_is_and_nothing_else_moves(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_rename_folder-renamed")
        old = await call("outlook_create_folder", name="Old")

        renamed = await call("outlook_rename_folder", folder_ref=old["uri"], name="Archive 2025")

        assert sent_json(graph, "PATCH", _folder_id(cast("str", old["uri"]))) == {
            "displayName": "Archive 2025"
        }
        assert renamed["uri"] == old["uri"]
        assert times_asked(graph, "POST", "/move") + times_asked(graph, "POST", "/copy") == 0

    async def test_a_folder_moves_to_deleted_items_only_after_mia_approves(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_delete_folder-created")
        temp = await call("outlook_create_folder", name="Temp")
        person = Person()

        deleted = await invoke_as(
            "outlook_delete_folder", {"folder_ref": temp["uri"]}, person=person
        )

        assert len(person.asked) == 1
        assert deleted.structured_content is not None
        (move,) = sent_jsons(graph, "POST", "/move")
        assert move == {
            "DestinationId": answer_of(
                "rec-tool-outlook_delete_folder-created", "GET", "/me/mailFolders/deleteditems"
            )["id"]
        }

    @pytest.mark.parametrize("built_in", ["inbox", "deleteditems"])
    async def test_a_built_in_folder_is_never_deleted(
        self, graph: respx.MockRouter, built_in: str
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_delete_folder-created")
        known = answer_of(
            "rec-tool-outlook_delete_folder-created", "GET", f"/me/mailFolders/{built_in}"
        )
        root = answer_of(
            "rec-tool-outlook_delete_folder-created", "GET", "/me/mailFolders/msgfolderroot"
        )
        _ = graph.get(f"{_FOLDERS}/{known['id']}").mock(
            return_value=httpx.Response(200, json=known | {"parentFolderId": root["id"]})
        )
        person = Person()

        advice = await refusal_of(
            "outlook_delete_folder",
            {"folder_ref": f"outlook:///folders/{known['id']}"},
            person=person,
        )

        assert "Nothing was deleted" in advice
        assert person.asked == []
        assert times_asked(graph, "POST", "/move") == 0

    async def test_two_folders_with_one_name_show_up_at_different_levels(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_browse_folders-same-name")
        top = await call("outlook_browse_folders", limit=50)
        projects = _folder(top, "seed-v1 Projects")
        inside = await call("outlook_browse_folders", parent=projects["uri"], limit=50)

        assert _rows(top, "folders", "display_name").count("seed-v1 Archive") == 1
        assert "seed-v1 Website Relaunch" not in _rows(top, "folders", "display_name")
        assert projects["child_folder_count"] == 2
        assert _rows(inside, "folders", "display_name") == [
            "seed-v1 Archive",
            "seed-v1 Website Relaunch",
        ]
        assert _folder(inside, "seed-v1 Archive")["uri"] != _folder(top, "seed-v1 Archive")["uri"]
        assert methods_asked(graph) == {"GET"}


class TestEmptyingDeletedItemsIsLeftToMia:
    async def test_the_assistant_has_no_tool_that_erases_mail_and_the_folder_tool_says_so(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_delete_folder-created")
        deleted_items = answer_of(
            "rec-tool-outlook_delete_folder-created", "GET", "/me/mailFolders/deleteditems"
        )
        _ = graph.get(f"{_FOLDERS}/{deleted_items['id']}").mock(
            return_value=httpx.Response(200, json=deleted_items)
        )

        advice = await advice_for(
            "outlook_delete_folder", folder_ref=f"outlook:///folders/{deleted_items['id']}"
        )

        assert "tell them to do that in Outlook" in advice
        assert {
            name
            for name in TOOL_NAMES
            if re.search(r"delete|purge|erase|empty|permanent|remove", name)
        } == _DELETING_TOOLS
        assert times_asked(graph, "POST", "/move") == 0


class TestWhatNoPresetCanDoToday:
    @pytest.mark.parametrize(
        "pair",
        [
            ("outlook_create_category", "outlook_mark_mail"),
            ("outlook_browse_folders", "outlook_create_mail_rule"),
        ],
        ids=["category-and-mail", "folders-and-rules"],
    )
    def test_no_preset_holds_both_tools_of_the_task(self, pair: tuple[str, str]) -> None:
        assert set(pair) <= set(TOOL_NAMES)
        assert [name for name, tools in PRESETS.items() if set(pair) <= set(tools)] == []

    def test_no_tool_renames_a_category(self) -> None:
        assert {name for name in TOOL_NAMES if "categor" in name} == {
            "outlook_create_category",
            "outlook_list_categories",
        }


class TestAnInboxRuleActsOnNewMailWithoutMia:
    async def test_an_old_rule_is_turned_off_and_stays_in_the_list(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_disable_mail_rule-off")
        rule = await call(
            "outlook_create_mail_rule",
            display_name="Receipts",
            sequence=10,
            conditions={"subject_contains": ["receipt"]},
            actions={"mark_as_read": True},
        )

        _ = await call("outlook_disable_mail_rule", rule_ref=rule["uri"], enabled=False)

        assert sent_jsons(graph, "PATCH", "")[0] == {"isEnabled": False}
        assert "DELETE" not in methods_asked(graph)

    async def test_a_rule_that_forwards_mail_asks_first_and_the_question_names_every_address(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_create_mail_rule-basic")
        person = Person()

        made = await invoke_as(
            "outlook_create_mail_rule",
            {
                "display_name": "CEO to Anna and Tom",
                "sequence": 10,
                "conditions": {"from_addresses": ["ceo@example.com"]},
                "actions": {"forward_to": ["anna@example.com", "tom@example.com"]},
            },
            person=person,
        )

        (question,) = person.asked
        assert "anna@example.com" in question
        assert "tom@example.com" in question
        assert made.structured_content is not None
        assert times_asked(graph, "POST", "/messageRules") == 1

    async def test_a_rule_is_erased_only_after_mia_approves(self, graph: respx.MockRouter) -> None:
        _ = serve(graph, "rec-tool-outlook_delete_mail_rule-created")
        rule = await call(
            "outlook_create_mail_rule",
            display_name="Receipts",
            sequence=10,
            conditions={"subject_contains": ["receipt"]},
            actions={"mark_as_read": True},
        )
        person = Person()

        _ = await invoke_as("outlook_delete_mail_rule", {"rule_ref": rule["uri"]}, person=person)

        assert len(person.asked) == 1
        assert "DELETE" in methods_asked(graph)

    async def test_a_rule_that_deletes_mail_moves_it_to_deleted_items_and_never_erases_it(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_create_mail_rule-delete-action")

        _ = await call(
            "outlook_create_mail_rule",
            display_name="Spam",
            sequence=10,
            conditions={"from_addresses": ["spam@example.com"]},
            actions={"delete": True},
        )

        actions = cast("dict[str, object]", sent_json(graph, "POST", "/messageRules")["actions"])
        assert actions == {"delete": True}

    async def test_a_rule_without_a_condition_is_created_for_every_new_message_without_a_question(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_create_mail_rule-no-condition")
        archive = answer_of(
            "rec-tool-outlook_delete_folder-created", "GET", "/me/mailFolders/archive"
        )
        _ = graph.get(f"{_FOLDERS}/archive").mock(return_value=httpx.Response(200, json=archive))
        person = Person()

        made = await invoke_as(
            "outlook_create_mail_rule",
            {
                "display_name": "Archive the rest",
                "sequence": 10,
                "actions": {"move_to_folder": "archive"},
            },
            person=person,
        )

        created = sent_json(graph, "POST", "/messageRules")
        assert made.structured_content is not None
        assert person.asked == []
        assert "conditions" not in created
        assert cast("dict[str, object]", created["actions"])["moveToFolder"] == archive["id"]

    async def test_a_rule_is_narrowed_in_place_with_the_whole_set_of_conditions(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_update_mail_rule-narrow")
        rule = await call(
            "outlook_create_mail_rule",
            display_name="Billing to Finance",
            sequence=10,
            conditions={"from_addresses": ["billing@example.com"]},
            actions={"mark_as_read": True},
        )

        _ = await call(
            "outlook_update_mail_rule",
            rule_ref=rule["uri"],
            conditions={"from_addresses": ["billing@example.com"], "subject_contains": ["invoice"]},
        )

        conditions = cast("dict[str, object]", sent_jsons(graph, "PATCH", "")[0]["conditions"])
        assert set(conditions) == {"fromAddresses", "subjectContains"}
        assert times_asked(graph, "POST", "/messageRules") == 1

    async def test_a_rule_that_is_off_is_turned_on_again_and_the_disable_tool_cannot_do_it(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_update_mail_rule-turn-on")
        rule = await call(
            "outlook_create_mail_rule",
            display_name="Receipts",
            sequence=10,
            conditions={"subject_contains": ["receipt"]},
            actions={"mark_as_read": True},
            is_enabled=False,
        )

        _ = await call("outlook_update_mail_rule", rule_ref=rule["uri"], is_enabled=True)
        advice = await advice_for("outlook_disable_mail_rule", rule_ref=rule["uri"], enabled=True)

        assert sent_jsons(graph, "PATCH", "")[0] == {"isEnabled": True}
        assert "false" in advice.lower()
        assert times_asked(graph, "POST", "/messageRules") == 1

    async def test_a_rule_that_outlook_locks_is_not_changed_and_the_tool_says_what_to_tell_mia(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_disable_mail_rule-off")
        rule = await call(
            "outlook_create_mail_rule",
            display_name="Company policy",
            sequence=10,
            conditions={"subject_contains": ["policy"]},
            actions={"mark_as_read": True},
        )
        stored = _the_rule_answer("rec-tool-outlook_disable_mail_rule-off", "GET")
        _ = _rule_route(routes, "GET").mock(
            return_value=httpx.Response(200, json=stored | {"isReadOnly": True})
        )

        advice = await advice_for("outlook_disable_mail_rule", rule_ref=rule["uri"], enabled=False)

        assert "marks this rule read-only" in advice
        assert "a read-only rule still runs, and can still forward mail" in advice
        assert "PATCH" not in methods_asked(graph)

    async def test_a_rule_that_forwards_to_a_name_is_refused_until_the_address_is_found(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_create_mail_rule-basic")
        _ = graph.get("/me").mock(side_effect=every_time({"id": "me", "mail": "mia@example.test"}))
        _ = graph.get("/me/people").mock(
            side_effect=every_time(
                {
                    "value": [
                        {
                            "id": "a",
                            "displayName": "Anna Meier",
                            "scoredEmailAddresses": [{"address": "anna@example.test"}],
                            "personType": {"class": "Person", "subclass": "OrganizationUser"},
                        }
                    ]
                }
            )
        )
        person = Person()
        rule = {"display_name": "CEO to Anna", "sequence": 10}

        refused = await refusal_of(
            "outlook_create_mail_rule",
            rule | {"actions": {"forward_to": ["Anna"]}},
            person=person,
        )
        found = await call("outlook_find_recipient", query="Anna", limit=5)
        address = cast("list[dict[str, str]]", found["candidates"])[0]["address"]
        _ = await invoke_as(
            "outlook_create_mail_rule",
            rule | {"actions": {"forward_to": [address]}},
            person=person,
        )

        assert "No rule was created" in refused
        assert "outlook_find_recipient" in refused
        assert len(person.asked) == 1
        assert address in person.asked[0]
        assert times_asked(graph, "POST", "/messageRules") == 1

    @pytest.mark.parametrize(
        ("approval", "told"),
        [("no", "was not confirmed"), ("unanswered", "received no answer")],
        ids=["declines", "chat-program-fails"],
    )
    async def test_a_rule_that_forwards_mail_is_not_made_without_a_yes(
        self, graph: respx.MockRouter, approval: str, told: str
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_create_mail_rule-basic")

        advice = await refusal_of(
            "outlook_create_mail_rule",
            {
                "display_name": "CEO to Anna",
                "sequence": 10,
                "conditions": {"from_addresses": ["ceo@example.com"]},
                "actions": _FORWARDING,
            },
            person=Person(approval=approval),
        )

        assert told in advice
        assert times_asked(graph, "POST", "/messageRules") == 0

    @pytest.mark.parametrize(
        ("approval", "told"),
        [("no", "was not confirmed"), ("unanswered", "received no answer")],
        ids=["declines", "chat-program-fails"],
    )
    async def test_a_rule_is_not_erased_without_a_yes(
        self, graph: respx.MockRouter, approval: str, told: str
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_delete_mail_rule-created")
        rule = await call(
            "outlook_create_mail_rule",
            display_name="Receipts",
            sequence=10,
            conditions={"subject_contains": ["receipt"]},
            actions={"mark_as_read": True},
        )

        advice = await refusal_of(
            "outlook_delete_mail_rule", {"rule_ref": rule["uri"]}, person=Person(approval=approval)
        )

        assert told in advice
        assert "DELETE" not in methods_asked(graph)

    @pytest.mark.parametrize(
        ("approval", "told"),
        [("no", "was not confirmed"), ("unanswered", "received no answer")],
        ids=["declines", "chat-program-fails"],
    )
    async def test_a_folder_is_not_deleted_without_a_yes(
        self, graph: respx.MockRouter, approval: str, told: str
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_delete_folder-created")
        temp = await call("outlook_create_folder", name="Temp")

        advice = await refusal_of(
            "outlook_delete_folder", {"folder_ref": temp["uri"]}, person=Person(approval=approval)
        )

        assert told in advice
        assert times_asked(graph, "POST", "/move") == 0

    async def test_unread_newsletters_are_filed_and_no_rule_is_made(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_list_mail-inbox")
        _ = serve(graph, "rec-tool-outlook_browse_folders-top")
        _ = moving_every_message(graph)
        listing = await call("outlook_list_mail", unread_only=True, limit=3)
        handled = _folder(await call("outlook_browse_folders", limit=50), "seed-v1 Handled")
        _ = _a_visible_folder(graph, handled)

        moved = await call(
            "outlook_move_mail", message_refs=_uris(listing), folder_ref=handled["uri"]
        )

        assert (moved["moved_count"], moved["failed_count"]) == (3, 0)
        assert not [path for path in paths_asked(graph) if "messageRules" in path]
        assert {
            request.method
            for request in requests_asked(graph)
            if not request.url.path.endswith("/move")
        } == {"GET"}

    async def test_an_address_from_a_newsletter_reaches_a_rule_only_through_a_question(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_create_mail_rule-basic")
        person = Person(approval="no")

        advice = await refusal_of(
            "outlook_create_mail_rule",
            {
                "display_name": "All mail",
                "sequence": 10,
                "actions": {"forward_to": ["outsider@example.net"]},
            },
            person=person,
        )

        assert "outsider@example.net" in person.asked[0]
        assert "was not confirmed" in advice
        assert "Every address must come from the user" in await tool_description(
            "outlook_create_mail_rule"
        )
        assert times_asked(graph, "POST", "/messageRules") == 0

    async def test_a_rule_that_is_gone_is_not_changed(self, graph: respx.MockRouter) -> None:
        routes = serve(graph, "rec-tool-outlook_update_mail_rule-rename")
        rule = await call(
            "outlook_create_mail_rule",
            display_name="Receipts",
            sequence=10,
            conditions={"subject_contains": ["receipt"]},
            actions={"mark_as_read": True},
        )
        _ = _rule_route(routes, "GET").mock(
            side_effect=answers({"status": 404, "body": "error.ErrorItemNotFound.json"})
        )

        advice = await advice_for("outlook_update_mail_rule", rule_ref=rule["uri"], is_enabled=True)

        assert (
            "Call outlook_get_mailbox_settings again to see the rules that are there now" in advice
        )
        assert "PATCH" not in methods_asked(graph)

    async def test_a_rule_that_erases_mail_for_good_keeps_its_action(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_update_mail_rule-rename")
        rule = await call(
            "outlook_create_mail_rule",
            display_name="Old junk",
            sequence=10,
            conditions={"subject_contains": ["junk"]},
            actions={"mark_as_read": True},
        )
        stored = _the_rule_answer("rec-tool-outlook_update_mail_rule-rename", "GET")
        _ = _rule_route(routes, "GET").mock(
            return_value=httpx.Response(
                200, json=stored | {"actions": {"permanentDelete": True}, "isReadOnly": False}
            )
        )

        advice = await advice_for(
            "outlook_update_mail_rule",
            rule_ref=rule["uri"],
            actions={"move_to_folder": "archive"},
        )

        assert "Tell the user to change the actions of this rule in Outlook" in advice
        assert "PATCH" not in methods_asked(graph)


class TestABatchWithAWrongValueMovesNothing:
    async def test_mail_named_for_two_folders_at_once_is_not_moved(
        self, graph: respx.MockRouter
    ) -> None:
        advice = await advice_for(
            "outlook_move_mail",
            message_refs=[_Q3_MESSAGE],
            destination="archive",
            folder_ref="outlook:///folders/FINANCE%3D",
        )

        assert "alternatives, not a pair" in advice
        assert graph.calls.call_count == 0

    async def test_mail_named_for_no_folder_is_not_moved(self, graph: respx.MockRouter) -> None:
        advice = await advice_for("outlook_move_mail", message_refs=[_Q3_MESSAGE])

        assert "was given no destination" in advice
        assert graph.calls.call_count == 0

    @pytest.mark.parametrize(
        ("folder", "told"),
        [
            ({"isHidden": True}, "mail moved into it disappears from their view"),
            (
                {"@odata.type": "#microsoft.graph.mailSearchFolder", "filterQuery": "x"},
                "A search folder is a saved query",
            ),
        ],
        ids=["hidden-folder", "saved-search"],
    )
    async def test_mail_is_not_filed_in_a_folder_that_cannot_hold_it(
        self, graph: respx.MockRouter, folder: dict[str, object], told: str
    ) -> None:
        _ = graph.get(f"{_FOLDERS}/ODD1=").mock(
            return_value=httpx.Response(200, json={"id": "ODD1=", "displayName": "Odd"} | folder)
        )
        moving = moving_every_message(graph)

        advice = await advice_for(
            "outlook_move_mail", message_refs=[_Q3_MESSAGE], folder_ref="outlook:///folders/ODD1%3D"
        )

        assert told in advice
        assert moving.call_count == 0


class TestMiaIsToldWhatHappenedWhenMicrosoftCannotDoWhatSheAsked:
    @pytest.mark.usefixtures("retry_sleeps")
    @pytest.mark.parametrize("row", sorted(FAULTS))
    async def test_a_folder_list_that_microsoft_refuses_tells_mia_why(
        self, graph: respx.MockRouter, row: str
    ) -> None:
        status, headers, body, told = FAULTS[row]
        _ = graph.get(_FOLDERS).mock(
            side_effect=answers({"status": status, "response_headers": headers, "body": body})
        )

        advice = await advice_for("outlook_browse_folders", limit=50)

        assert told in advice

    @pytest.mark.parametrize("fault", ["fails", "no-answer-in-time", "never-ends"])
    async def test_a_folder_list_that_microsoft_cannot_finish_is_tried_once_more(
        self, graph: respx.MockRouter, fault: str
    ) -> None:
        route = serve(graph, "rec-tool-outlook_browse_folders-top")[("GET", _FOLDERS)]
        recorded = route.side_effect
        failures = {
            "fails": answers({"status": 500, "body": "error.generalException.json"}),
            "no-answer-in-time": _timing_out,
            "never-ends": every_time(
                {"value": [], "@odata.nextLink": f"{_GRAPH}{_FOLDERS}?$skip=5"}
            ),
        }
        _ = route.mock(side_effect=failures[fault])

        first = await advice_for("outlook_browse_folders", limit=50)
        _ = route.mock(side_effect=recorded)
        second = await call("outlook_browse_folders", limit=50)

        assert "Retry once" in first
        assert _rows(second, "folders", "display_name") == _RECORDED_FOLDER_NAMES

    async def test_one_busy_answer_is_waited_out_and_the_folders_arrive(
        self, graph: respx.MockRouter, retry_sleeps: RecordedSleeps
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_browse_folders-top")
        _ = routes[("GET", _FOLDERS)].mock(
            side_effect=[response(_BUSY_WRITE | {"status": 429}), _recorded_folders()]
        )

        found = await call("outlook_browse_folders", limit=50)

        assert "Inbox" in _rows(found, "folders", "display_name")
        assert len(cast("list[object]", found["folders"])) == len(_RECORDED_FOLDER_NAMES)
        assert retry_sleeps.delays == [30.0]

    @pytest.mark.usefixtures("retry_sleeps")
    @pytest.mark.parametrize("row", sorted(FAULTS))
    async def test_a_move_that_microsoft_refuses_tells_mia_why_and_does_not_say_that_it_moved(
        self, graph: respx.MockRouter, row: str
    ) -> None:
        status, headers, body, told = FAULTS[row]
        move = graph.post(path__regex=r".*/messages/[^/]+/move$").mock(
            side_effect=answers({"status": status, "response_headers": headers, "body": body})
        )

        advice = await advice_for(
            "outlook_move_mail", message_refs=[_Q3_MESSAGE], destination="archive"
        )

        assert told in advice
        assert "move" not in advice
        assert move.call_count == 1

    @pytest.mark.parametrize(
        ("tool", "arguments", "path"),
        [
            (
                "outlook_create_mail_rule",
                {
                    "display_name": "CEO to Anna",
                    "sequence": 10,
                    "conditions": {"from_addresses": ["ceo@example.com"]},
                    "actions": _FORWARDING,
                },
                "/me/mailFolders/inbox/messageRules",
            ),
            ("outlook_create_folder", {"name": "Alpha"}, _FOLDERS),
        ],
        ids=["forwarding-rule", "folder"],
    )
    async def test_a_change_that_microsoft_asks_to_wait_for_is_not_reported_as_not_made(
        self, graph: respx.MockRouter, tool: str, arguments: dict[str, object], path: str
    ) -> None:
        create = graph.post(path).mock(side_effect=answers(_BUSY_WRITE))

        advice = await refusal_of(tool, arguments)

        assert "asked to be left alone for 30 seconds" in advice
        assert "no folder was created" not in advice.lower()
        assert create.call_count == 1

    async def test_a_folder_that_was_made_again_is_found_again(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(f"{_FOLDERS}/OLD1=").mock(
            side_effect=answers({"status": 404, "body": "error.ErrorItemNotFound.json"})
        )
        stale = await advice_for(
            "outlook_move_mail",
            message_refs=[_Q3_MESSAGE],
            folder_ref="outlook:///folders/OLD1%3D",
        )
        _ = graph.get(f"{_FOLDERS}/NEW1=").mock(
            return_value=httpx.Response(200, json={"id": "NEW1=", "displayName": "Finance"})
        )
        _ = moving_every_message(graph)

        moved = await call(
            "outlook_move_mail",
            message_refs=[_Q3_MESSAGE],
            folder_ref="outlook:///folders/NEW1%3D",
        )

        assert "Call outlook_browse_folders again" in stale
        assert moved["moved_count"] == 1

    async def test_a_batch_of_messages_that_are_all_gone_is_reported(
        self, graph: respx.MockRouter
    ) -> None:
        gone = graph.post(path__regex=r".*/messages/[^/]+/move$").mock(
            side_effect=answers({"status": 404, "body": "error.ErrorItemNotFound.json"})
        )

        advice = await advice_for(
            "outlook_move_mail",
            message_refs=[_Q3_MESSAGE, _Q3_MESSAGE.replace("UVs", "UVt")],
            destination="archive",
        )

        assert "tell the user that the message is not in this mailbox now" in advice
        assert gone.call_count == 2

    @pytest.mark.parametrize(
        "failure",
        [
            response({"status": 500, "body": "error.generalException.json"}),
            httpx.ReadTimeout("no answer in time"),
            response(
                {
                    "status": 200,
                    "headers": {"Content-Type": "text/html"},
                    "body": "page.notData.html",
                }
            ),
        ],
        ids=["fails", "no-answer-in-time", "unreadable"],
    )
    async def test_a_move_that_microsoft_fails_is_not_repeated_for_any_message(
        self, graph: respx.MockRouter, failure: httpx.Response | Exception
    ) -> None:
        moving = graph.post(path__regex=r".*/messages/[^/]+/move$").mock(
            side_effect=raising(failure)
        )
        refs = [_Q3_MESSAGE.replace("UVs", prefix) for prefix in ("UVa", "UVb", "UVc")]

        advice = await advice_for("outlook_move_mail", message_refs=refs, destination="archive")

        assert _OUTCOME_UNKNOWN in advice
        assert "use outlook_read_mail or outlook_list_mail" in advice
        assert moving.call_count == 3

    async def test_a_marking_that_microsoft_fails_for_every_message_is_reported_twice_the_same(
        self, graph: respx.MockRouter
    ) -> None:
        patch = graph.route(method="PATCH", path__regex=r".*/messages/[^/]+$").mock(
            side_effect=answers({"status": 500, "body": "error.generalException.json"})
        )
        refs = [_Q3_MESSAGE.replace("UVs", prefix) for prefix in ("UVa", "UVb")]

        first = await advice_for("outlook_mark_mail", message_refs=refs, is_read=True)
        second = await advice_for("outlook_mark_mail", message_refs=refs, is_read=True)

        assert first == second
        assert "stop and report it" in second
        assert patch.call_count == 4

    @pytest.mark.parametrize(
        ("tool", "method", "path", "arguments"),
        [
            ("outlook_create_folder", "POST", _FOLDERS, {"name": "Alpha"}),
            (
                "outlook_create_category",
                "POST",
                "/me/outlook/masterCategories",
                {"name": "Follow-up Q4"},
            ),
        ],
        ids=["folder", "category"],
    )
    async def test_a_name_that_mia_already_uses_is_not_used_twice(
        self,
        graph: respx.MockRouter,
        tool: str,
        method: str,
        path: str,
        arguments: dict[str, object],
    ) -> None:
        taken = graph.route(method=method, path=path).mock(
            return_value=httpx.Response(
                409, json={"error": {"code": "ErrorFolderExists", "message": "The name is used."}}
            )
        )

        advice = await advice_for(tool, **arguments)

        assert "an item at that level already has the same name" in advice
        assert "Change the name" in advice
        assert taken.call_count == 1

    async def test_a_rename_to_a_name_that_is_used_changes_nothing(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_rename_folder-renamed")
        old = await call("outlook_create_folder", name="Old")
        _ = next(route for (verb, _path), route in routes.items() if verb == "PATCH").mock(
            return_value=httpx.Response(
                409, json={"error": {"code": "ErrorFolderExists", "message": "The name is used."}}
            )
        )

        advice = await advice_for("outlook_rename_folder", folder_ref=old["uri"], name="Alpha")

        assert "an item at that level already has the same name" in advice

    async def test_a_rule_that_microsoft_rejects_as_invalid_is_not_repeated_and_gives_the_reason(
        self, graph: respx.MockRouter
    ) -> None:
        rejected = graph.post("/me/mailFolders/inbox/messageRules").mock(
            return_value=httpx.Response(
                400,
                json={"error": {"code": "ErrorInvalidRule", "message": "The folder is not valid."}},
            )
        )

        advice = await advice_for(
            "outlook_create_mail_rule",
            display_name="Billing to Finance",
            sequence=10,
            conditions={"from_addresses": ["billing@example.com"]},
            actions={"mark_as_read": True},
        )

        assert "The folder is not valid." in advice
        assert "the call will fail the same way" in advice
        assert rejected.call_count == 1

    @pytest.mark.parametrize(
        "failure",
        [
            response({"status": 500, "body": "error.generalException.json"}),
            httpx.ReadTimeout("no answer in time"),
        ],
        ids=["fails", "no-answer-in-time"],
    )
    async def test_a_copy_that_microsoft_fails_is_not_made_twice(
        self, graph: respx.MockRouter, failure: httpx.Response | Exception
    ) -> None:
        copying = graph.post(path__regex=r".*/messages/[^/]+/copy$").mock(
            side_effect=raising(failure)
        )

        advice = await advice_for(
            "outlook_copy_mail", message_refs=[_Q3_MESSAGE], destination="archive"
        )

        assert _OUTCOME_UNKNOWN in advice
        assert "use outlook_read_mail or outlook_list_mail" in advice
        assert copying.call_count == 1

    async def test_a_message_that_is_gone_is_not_copied(self, graph: respx.MockRouter) -> None:
        _ = graph.post(path__regex=r".*/messages/[^/]+/copy$").mock(
            side_effect=answers({"status": 404, "body": "error.ErrorItemNotFound.json"})
        )

        advice = await advice_for(
            "outlook_copy_mail", message_refs=[_Q3_MESSAGE], destination="archive"
        )

        assert "No message was copied" in advice
        assert "tell the user that the message is not in this mailbox now" in advice


class TestAPersonPlansMoreThanOneStepInOneRequest:
    async def test_a_reply_is_drafted_and_the_message_it_answers_is_filed_and_nothing_is_sent(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_draft_reply-reply")
        _ = serve(graph, "rec-tool-outlook_move_mail-archive")

        draft = await call(
            "outlook_draft_reply",
            message_ref=_Q3_MESSAGE,
            mode="reply",
            body="I will sign it on Friday.",
        )
        moved = await call("outlook_move_mail", message_refs=[_Q3_MESSAGE], destination="archive")

        assert _rows(draft, "to", "address") == ["anna@example.test"]
        assert sent_json(graph, "PATCH", "")["body"] == {
            "contentType": "html",
            "content": "<p>I will sign it on Friday.</p>",
        }
        assert (moved["moved_count"], _rows(moved, "messages", "new_uri")) == (1, [_Q3_MESSAGE])
        assert not [path for path in paths_asked(graph) if path.endswith("/send")]

    async def test_an_invoice_is_filed_and_a_note_about_it_is_drafted_and_nothing_is_sent(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_move_mail-invoice")
        found = await call("outlook_search_mail", subject="Invoice Alpine Print", limit=3)
        invoice = cast("list[dict[str, object]]", found["messages"])[0]
        clients = _folder(await call("outlook_browse_folders", limit=50), "seed-v1 Clients")
        sender = cast("dict[str, str]", invoice["sender"])["address"]

        moved = await call(
            "outlook_move_mail",
            message_refs=[cast("str", invoice["uri"])],
            folder_ref=clients["uri"],
        )
        note = await call(
            "outlook_draft_mail",
            to=[sender],
            subject="Invoice filed",
            body="The invoice is filed in Clients.",
        )

        assert (moved["moved_count"], moved["destination"]) == (1, "seed-v1 Clients")
        assert note["uri"]
        created = sent_json(graph, "POST", "/me/messages")
        assert created["subject"] == "Invoice filed"
        assert created["toRecipients"] == [{"emailAddress": {"address": sender}}]
        assert cast("dict[str, object]", created["body"])["content"] == (
            "<p>The invoice is filed in Clients.</p>"
        )
        assert not [path for path in paths_asked(graph) if path.endswith("/send")]


_GRAPH = "https://graph.microsoft.com/v1.0"
_RECORDED_FOLDER_NAMES = [
    cast("str", folder["displayName"])
    for folder in cast(
        "list[dict[str, object]]",
        answer_of("rec-tool-outlook_browse_folders-top", "GET", "/me/mailFolders")["value"],
    )
]


def _recorded_folders() -> httpx.Response:
    return httpx.Response(
        200, json=answer_of("rec-tool-outlook_browse_folders-top", "GET", "/me/mailFolders")
    )


def _timing_out(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("no answer in time", request=request)
