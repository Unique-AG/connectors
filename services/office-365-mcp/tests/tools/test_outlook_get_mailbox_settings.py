from collections.abc import Mapping
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.tools import Tool
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden
from office_365_mcp.shared.handles import MailFolderHandle, MailRuleHandle, mail_folder_handle
from office_365_mcp.shared.rules import MailRule, RuleActions
from office_365_mcp.tools import outlook_get_mailbox_settings as settings_tool

from .conftest import GRAPH_V1

_RULES = "/me/mailFolders/inbox/messageRules"
_SETTINGS = "/me/mailboxSettings"
_CATEGORIES = "/me/outlook/masterCategories"

_RULE_ID = "AQAAAJSYNTHETIC-rule-one"
_OTHER_RULE_ID = "AQAAAJSYNTHETIC-rule-two"
_ARCHIVE_FOLDER_ID = "AQMkADAwSYNTHETIC-archive"
_COPY_FOLDER_ID = "AQMkADAwSYNTHETIC-copy"

_OUTSIDE = "collector@elsewhere.invalid"
_INSIDE = "deputy@example.invalid"

_PREFERENCE_PARTS = ("time_zone", "working_hours", "language", "archive_folder_uri")


def _recipient(address: str | None, *, name: str | None = None) -> dict[str, object]:
    return {"emailAddress": {"address": address, "name": name}}


def _rule_payload(
    rule_id: str = _RULE_ID,
    *,
    display_name: str | None = "Newsletters",
    is_enabled: bool | None = True,
    sequence: int | None = 1,
    is_read_only: bool | None = False,
    has_error: bool | None = False,
    conditions: dict[str, object] | None = None,
    exceptions: dict[str, object] | None = None,
    actions: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": rule_id,
        "displayName": display_name,
        "isEnabled": is_enabled,
        "sequence": sequence,
        "isReadOnly": is_read_only,
        "hasError": has_error,
    }
    if conditions is not None:
        payload["conditions"] = conditions
    if exceptions is not None:
        payload["exceptions"] = exceptions
    if actions is not None:
        payload["actions"] = actions
    return payload


def _reply_payload(
    *,
    status: str | None = "scheduled",
    external_audience: str | None = "all",
    internal: str | None = "<p>Back on the 14th.</p>",
    external: str | None = "<p>Away until the 14th. Reach Grace at grace@example.invalid.</p>",
    scheduled: bool = True,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": status,
        "externalAudience": external_audience,
        "internalReplyMessage": internal,
        "externalReplyMessage": external,
    }
    if scheduled:
        payload["scheduledStartDateTime"] = {
            "dateTime": "2026-09-01T07:00:00.0000000",
            "timeZone": "UTC",
        }
        payload["scheduledEndDateTime"] = {
            "dateTime": "2026-09-14T17:00:00.0000000",
            "timeZone": "W. Europe Standard Time",
        }
    return payload


def _preferences_payload(
    *,
    time_zone: str | None = "W. Europe Standard Time",
    archive_folder: str | None = _ARCHIVE_FOLDER_ID,
) -> dict[str, object]:
    return {
        "timeZone": time_zone,
        "language": {"locale": "de-CH", "displayName": "German (Switzerland)"},
        "workingHours": {
            "daysOfWeek": ["monday", "tuesday", "wednesday", "thursday", "friday"],
            "startTime": "08:00:00.0000000",
            "endTime": "17:00:00.0000000",
            "timeZone": {"name": "W. Europe Standard Time"},
        },
        "archiveFolder": archive_folder,
    }


def _page(*items: dict[str, object], next_link: str | None = None) -> httpx.Response:
    body: dict[str, object] = {"value": list(items)}
    if next_link is not None:
        body["@odata.nextLink"] = next_link
    return httpx.Response(200, json=body)


def _settings_response(
    reply: dict[str, object] | None, preferences: dict[str, object] | None = None
) -> httpx.Response:
    body: dict[str, object] = {} if reply is None else {"automaticRepliesSetting": reply}
    return httpx.Response(200, json={**body, **(preferences or {})})


def _actions(rule: MailRule) -> RuleActions:
    assert rule.actions is not None, "the rule reported no actions"
    return rule.actions


def _described(tool: Tool) -> dict[str, str | None]:
    answer = cast("Mapping[str, object]", tool.output_schema)
    definitions = cast("Mapping[str, Mapping[str, object]]", answer.get("$defs", {}))
    models: dict[str, Mapping[str, object]] = {"answer": answer, **definitions}
    return {
        f"{model}.{name}": cast("Mapping[str, str | None]", field).get("description")
        for model, schema in models.items()
        for name, field in cast("Mapping[str, object]", schema.get("properties", {})).items()
    }


@pytest.fixture
async def published(transport: httpx.AsyncClient) -> Tool:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    settings_tool.register(mcp, transport)
    tool = await mcp.get_tool(settings_tool.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return tool


@pytest.fixture
def rules(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_RULES).mock(return_value=_page())


@pytest.fixture
def mailbox(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_SETTINGS).mock(
        return_value=_settings_response(_reply_payload(), _preferences_payload())
    )


@pytest.fixture
def categories(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_CATEGORIES).mock(return_value=_page())


class TestWhatItAsksGraphFor:
    async def test_the_default_spends_one_request_on_each_of_the_three_resources(
        self,
        client: GraphServiceClient,
        rules: respx.Route,
        mailbox: respx.Route,
        categories: respx.Route,
    ) -> None:
        _ = await settings_tool.get_mailbox_settings(client)

        assert rules.call_count == 1
        assert mailbox.call_count == 1
        assert categories.call_count == 1

    @pytest.mark.parametrize(
        ("include", "asked"),
        [
            ("rules", _RULES),
            ("replies", _SETTINGS),
            ("preferences", _SETTINGS),
            ("categories", _CATEGORIES),
        ],
    )
    async def test_one_question_spends_one_graph_request(
        self,
        client: GraphServiceClient,
        rules: respx.Route,
        mailbox: respx.Route,
        categories: respx.Route,
        include: settings_tool.Include,
        asked: str,
    ) -> None:
        _ = await settings_tool.get_mailbox_settings(client, include=include)

        called = {
            _RULES: rules.call_count,
            _SETTINGS: mailbox.call_count,
            _CATEGORIES: categories.call_count,
        }
        assert called == {path: (1 if path == asked else 0) for path in called}

    async def test_the_rules_are_the_inbox_folders_by_its_well_known_name(
        self, client: GraphServiceClient, rules: respx.Route
    ) -> None:
        _ = await settings_tool.get_mailbox_settings(client, include="rules")

        assert rules.calls.last.request.url.path.endswith("/me/mailFolders/inbox/messageRules")

    async def test_it_asks_for_the_rule_properties_the_answer_reads(
        self, client: GraphServiceClient, rules: respx.Route
    ) -> None:
        _ = await settings_tool.get_mailbox_settings(client, include="rules")

        params = rules.calls.last.request.url.params
        assert params["$select"].split(",") == [
            "id",
            "displayName",
            "isEnabled",
            "sequence",
            "isReadOnly",
            "hasError",
            "conditions",
            "exceptions",
            "actions",
        ]

    async def test_it_asks_the_mailbox_for_the_automatic_reply_alone(
        self, client: GraphServiceClient, mailbox: respx.Route
    ) -> None:
        _ = await settings_tool.get_mailbox_settings(client, include="replies")

        params = mailbox.calls.last.request.url.params
        assert params["$select"].split(",") == ["automaticRepliesSetting"]

    async def test_it_reads_the_preferences_from_the_whole_resource_with_no_select(
        self, client: GraphServiceClient, mailbox: respx.Route
    ) -> None:
        _ = await settings_tool.get_mailbox_settings(client, include="preferences")

        assert "$select" not in mailbox.calls.last.request.url.params

    @pytest.mark.usefixtures("rules", "categories")
    async def test_the_default_reads_the_reply_and_the_preferences_in_one_request(
        self, client: GraphServiceClient, mailbox: respx.Route
    ) -> None:
        _ = await settings_tool.get_mailbox_settings(client, include="all")

        assert mailbox.call_count == 1
        assert "$select" not in mailbox.calls.last.request.url.params


class TestWhatARuleSays:
    async def test_a_forwarding_rule_names_the_addresses_it_forwards_to(
        self, client: GraphServiceClient, rules: respx.Route
    ) -> None:
        rules.mock(
            return_value=_page(
                _rule_payload(
                    actions={"forwardTo": [_recipient(_OUTSIDE)], "stopProcessingRules": False}
                )
            )
        )

        answer = await settings_tool.get_mailbox_settings(client, include="rules")

        assert answer.rules is not None
        assert _actions(answer.rules[0]).forward_to == [_OUTSIDE]

    async def test_a_redirect_and_an_attachment_forward_are_reported_apart_from_a_forward(
        self, client: GraphServiceClient, rules: respx.Route
    ) -> None:
        rules.mock(
            return_value=_page(
                _rule_payload(
                    actions={
                        "forwardTo": [_recipient(_OUTSIDE)],
                        "redirectTo": [_recipient(_INSIDE)],
                        "forwardAsAttachmentTo": [_recipient("audit@example.invalid")],
                    }
                )
            )
        )

        rule = (await settings_tool.get_mailbox_settings(client, include="rules")).rules

        assert rule is not None
        actions = _actions(rule[0])
        assert actions.forward_to == [_OUTSIDE]
        assert actions.redirect_to == [_INSIDE]
        assert actions.forward_as_attachment_to == ["audit@example.invalid"]

    async def test_a_recipient_with_no_address_is_named_rather_than_dropped(
        self, client: GraphServiceClient, rules: respx.Route
    ) -> None:
        rules.mock(
            return_value=_page(
                _rule_payload(
                    actions={
                        "forwardTo": [
                            _recipient(None, name="Archive Service"),
                            _recipient(_OUTSIDE, name="Collector"),
                        ]
                    }
                )
            )
        )

        rule = (await settings_tool.get_mailbox_settings(client, include="rules")).rules

        assert rule is not None
        assert _actions(rule[0]).forward_to == ["Archive Service", _OUTSIDE]

    async def test_each_rule_carries_the_handle_that_names_it(
        self, client: GraphServiceClient, rules: respx.Route
    ) -> None:
        rules.mock(
            return_value=_page(
                _rule_payload(), _rule_payload(_OTHER_RULE_ID, display_name="Invoices")
            )
        )

        answer = await settings_tool.get_mailbox_settings(client, include="rules")

        assert answer.rules is not None
        assert [rule.uri for rule in answer.rules] == [
            MailRuleHandle(_RULE_ID).uri,
            MailRuleHandle(_OTHER_RULE_ID).uri,
        ]

    async def test_it_reports_the_state_graph_gave_the_rule(
        self, client: GraphServiceClient, rules: respx.Route
    ) -> None:
        rules.mock(
            return_value=_page(
                _rule_payload(
                    display_name="Send to personal",
                    is_enabled=False,
                    sequence=4,
                    is_read_only=True,
                    has_error=True,
                )
            )
        )

        rule = (await settings_tool.get_mailbox_settings(client, include="rules")).rules

        assert rule is not None
        assert rule[0].display_name == "Send to personal"
        assert rule[0].is_enabled is False
        assert rule[0].sequence == 4
        assert rule[0].is_read_only is True
        assert rule[0].has_error is True

    async def test_a_rule_that_files_deletes_and_stops_reports_each_of_them(
        self, client: GraphServiceClient, rules: respx.Route
    ) -> None:
        rules.mock(
            return_value=_page(
                _rule_payload(
                    actions={
                        "moveToFolder": _ARCHIVE_FOLDER_ID,
                        "delete": True,
                        "markAsRead": True,
                        "stopProcessingRules": True,
                    }
                )
            )
        )

        rule = (await settings_tool.get_mailbox_settings(client, include="rules")).rules

        assert rule is not None
        actions = _actions(rule[0])
        assert actions.move_to_folder == _ARCHIVE_FOLDER_ID
        assert actions.delete is True
        assert actions.mark_as_read is True
        assert actions.stop_processing_rules is True

    async def test_a_rule_that_categorizes_copies_and_sets_the_importance_reports_each_of_them(
        self, client: GraphServiceClient, rules: respx.Route
    ) -> None:
        rules.mock(
            return_value=_page(
                _rule_payload(
                    actions={
                        "assignCategories": ["Partner", "Urgent"],
                        "copyToFolder": _COPY_FOLDER_ID,
                        "markImportance": "high",
                        "moveToFolder": _ARCHIVE_FOLDER_ID,
                    }
                )
            )
        )

        rule = (await settings_tool.get_mailbox_settings(client, include="rules")).rules

        assert rule is not None
        actions = _actions(rule[0])
        assert actions.assign_categories == ["Partner", "Urgent"]
        assert actions.copy_to_folder == _COPY_FOLDER_ID
        assert actions.mark_importance == "high"
        assert actions.move_to_folder == _ARCHIVE_FOLDER_ID
        assert actions.permanent_delete is None

    @pytest.mark.parametrize("importance", ["low", "normal", "high"])
    async def test_every_importance_a_rule_sets_is_reported_by_its_own_name(
        self, client: GraphServiceClient, rules: respx.Route, importance: str
    ) -> None:
        rules.mock(return_value=_page(_rule_payload(actions={"markImportance": importance})))

        rule = (await settings_tool.get_mailbox_settings(client, include="rules")).rules

        assert rule is not None
        assert _actions(rule[0]).mark_importance == importance

    async def test_a_permanent_erase_is_reported_apart_from_a_delete_to_deleted_items(
        self, client: GraphServiceClient, rules: respx.Route
    ) -> None:
        rules.mock(
            return_value=_page(
                _rule_payload(actions={"delete": False, "permanentDelete": True}),
                _rule_payload(_OTHER_RULE_ID, actions={"delete": True, "permanentDelete": False}),
            )
        )

        rule = (await settings_tool.get_mailbox_settings(client, include="rules")).rules

        assert rule is not None
        assert [(_actions(row).delete, _actions(row).permanent_delete) for row in rule] == [
            (False, True),
            (True, False),
        ]

    async def test_a_rule_that_permanently_deletes_still_reports_it(
        self, client: GraphServiceClient, rules: respx.Route
    ) -> None:
        rules.mock(return_value=_page(_rule_payload(actions={"permanentDelete": True})))

        answer = await settings_tool.get_mailbox_settings(client, include="rules")

        assert answer.rules is not None
        assert _actions(answer.rules[0]).permanent_delete is True
        published = cast("list[Mapping[str, object]]", answer.model_dump(mode="json")["rules"])
        assert published[0]["actions"] == {"permanent_delete": True}

    async def test_a_rule_that_does_none_of_these_says_false_rather_than_nothing(
        self, client: GraphServiceClient, rules: respx.Route
    ) -> None:
        rules.mock(
            return_value=_page(
                _rule_payload(
                    actions={"delete": False, "markAsRead": False, "assignCategories": []}
                )
            )
        )

        rule = (await settings_tool.get_mailbox_settings(client, include="rules")).rules

        assert rule is not None
        actions = _actions(rule[0])
        assert actions.delete is False
        assert actions.mark_as_read is False
        assert actions.forward_to is None
        assert actions.move_to_folder is None
        assert actions.assign_categories is None
        assert actions.copy_to_folder is None
        assert actions.mark_importance is None

    async def test_a_rule_graph_reported_no_actions_for_is_still_listed(
        self, client: GraphServiceClient, rules: respx.Route
    ) -> None:
        rules.mock(return_value=_page(_rule_payload(actions=None)))

        rule = (await settings_tool.get_mailbox_settings(client, include="rules")).rules

        assert rule is not None
        assert rule[0].uri == MailRuleHandle(_RULE_ID).uri
        assert rule[0].actions is None

    async def test_a_rule_is_published_in_one_shape_with_its_actions_nested(
        self, client: GraphServiceClient, rules: respx.Route
    ) -> None:
        rules.mock(
            return_value=_page(
                _rule_payload(
                    actions={"forwardTo": [_recipient(_OUTSIDE)], "markAsRead": True},
                )
            )
        )

        answer = await settings_tool.get_mailbox_settings(client, include="rules")

        published = cast("list[Mapping[str, object]]", answer.model_dump(mode="json")["rules"])
        assert set(published[0]) == set(MailRule.model_fields)
        assert published[0]["actions"] == {"forward_to": [_OUTSIDE], "mark_as_read": True}

    @pytest.mark.usefixtures("rules")
    async def test_a_mailbox_with_no_rules_answers_an_empty_list(
        self, client: GraphServiceClient
    ) -> None:
        answer = await settings_tool.get_mailbox_settings(client, include="rules")

        assert answer.rules == []
        assert answer.rules_capped is False


class TestWhatTriggersARule:
    async def test_a_rule_reports_the_conditions_graph_gave_it(
        self, client: GraphServiceClient, rules: respx.Route
    ) -> None:
        rules.mock(
            return_value=_page(
                _rule_payload(
                    conditions={
                        "subjectContains": ["invoice", "receipt"],
                        "fromAddresses": [_recipient(_OUTSIDE)],
                        "hasAttachments": True,
                        "importance": "high",
                        "withinSizeRange": {"minimumSize": 100},
                    }
                )
            )
        )

        rule = (await settings_tool.get_mailbox_settings(client, include="rules")).rules

        assert rule is not None
        assert rule[0].conditions is not None
        assert rule[0].conditions.subject_contains == ["invoice", "receipt"]
        assert rule[0].conditions.from_addresses == [_OUTSIDE]
        assert rule[0].conditions.has_attachments is True
        assert rule[0].conditions.importance == "high"
        assert rule[0].conditions.within_size_range is not None
        assert rule[0].conditions.within_size_range.minimum_kb == 100
        assert rule[0].exceptions is None

    async def test_the_exceptions_of_a_rule_are_reported_apart_from_its_conditions(
        self, client: GraphServiceClient, rules: respx.Route
    ) -> None:
        rules.mock(
            return_value=_page(
                _rule_payload(
                    conditions={"senderContains": ["newsletter"]},
                    exceptions={"sentToMe": True, "categories": ["Important"]},
                )
            )
        )

        rule = (await settings_tool.get_mailbox_settings(client, include="rules")).rules

        assert rule is not None
        assert rule[0].conditions is not None
        assert rule[0].conditions.sender_contains == ["newsletter"]
        assert rule[0].conditions.sent_to_me is None
        assert rule[0].exceptions is not None
        assert rule[0].exceptions.sent_to_me is True
        assert rule[0].exceptions.categories == ["Important"]
        assert rule[0].exceptions.sender_contains is None

    async def test_only_the_predicates_the_rule_sets_reach_the_published_answer(
        self, client: GraphServiceClient, rules: respx.Route
    ) -> None:
        rules.mock(
            return_value=_page(
                _rule_payload(
                    conditions={
                        "subjectContains": ["invoice"],
                        "bodyContains": [],
                        "fromAddresses": [],
                        "hasAttachments": None,
                        "importance": None,
                    },
                    exceptions={"isAutomaticReply": True},
                )
            )
        )

        answer = await settings_tool.get_mailbox_settings(client, include="rules")

        published = cast("list[Mapping[str, object]]", answer.model_dump(mode="json")["rules"])
        assert published[0]["conditions"] == {"subject_contains": ["invoice"]}
        assert published[0]["exceptions"] == {"is_automatic_reply": True}

    @pytest.mark.parametrize("conditions", [None, {}, {"subjectContains": [], "isSigned": None}])
    async def test_a_rule_with_nothing_set_has_null_conditions_and_null_exceptions(
        self, client: GraphServiceClient, rules: respx.Route, conditions: dict[str, object] | None
    ) -> None:
        rules.mock(return_value=_page(_rule_payload(conditions=conditions, exceptions=conditions)))

        rule = (await settings_tool.get_mailbox_settings(client, include="rules")).rules

        assert rule is not None
        assert rule[0].conditions is None
        assert rule[0].exceptions is None

    async def test_the_conditions_and_the_actions_of_one_rule_stay_together(
        self, client: GraphServiceClient, rules: respx.Route
    ) -> None:
        rules.mock(
            return_value=_page(
                _rule_payload(
                    conditions={"bodyOrSubjectContains": ["urgent"]},
                    actions={"forwardTo": [_recipient(_OUTSIDE)], "markAsRead": True},
                )
            )
        )

        rule = (await settings_tool.get_mailbox_settings(client, include="rules")).rules

        assert rule is not None
        assert rule[0].conditions is not None
        assert rule[0].conditions.body_or_subject_contains == ["urgent"]
        assert _actions(rule[0]).forward_to == [_OUTSIDE]
        assert _actions(rule[0]).mark_as_read is True


class TestTheAutomaticReply:
    @pytest.mark.usefixtures("mailbox")
    async def test_it_reports_the_status_the_audience_and_both_bodies(
        self, client: GraphServiceClient
    ) -> None:
        answer = await settings_tool.get_mailbox_settings(client, include="replies")

        reply = answer.automatic_reply
        assert reply is not None
        assert reply.status == "scheduled"
        assert reply.external_audience == "all"
        assert reply.internal_reply_message == "<p>Back on the 14th.</p>"
        assert reply.external_reply_message is not None
        assert "grace@example.invalid" in reply.external_reply_message

    @pytest.mark.usefixtures("mailbox")
    async def test_the_schedule_carries_the_zone_each_end_is_expressed_in(
        self, client: GraphServiceClient
    ) -> None:
        answer = await settings_tool.get_mailbox_settings(client, include="replies")

        reply = answer.automatic_reply
        assert reply is not None
        assert reply.scheduled_start is not None
        assert reply.scheduled_start.date_time == "2026-09-01T07:00:00.0000000"
        assert reply.scheduled_start.time_zone == "UTC"
        assert reply.scheduled_end is not None
        assert reply.scheduled_end.time_zone == "W. Europe Standard Time"

    @pytest.mark.parametrize(
        ("sent", "reported"),
        [("disabled", "disabled"), ("alwaysEnabled", "alwaysEnabled"), ("scheduled", "scheduled")],
    )
    async def test_every_status_microsoft_publishes_is_reported_by_its_own_name(
        self, client: GraphServiceClient, mailbox: respx.Route, sent: str, reported: str
    ) -> None:
        mailbox.mock(return_value=_settings_response(_reply_payload(status=sent)))

        answer = await settings_tool.get_mailbox_settings(client, include="replies")

        assert answer.automatic_reply is not None
        assert answer.automatic_reply.status == reported

    @pytest.mark.parametrize("audience", ["none", "contactsOnly", "all"])
    async def test_every_external_audience_is_reported_by_its_own_name(
        self, client: GraphServiceClient, mailbox: respx.Route, audience: str
    ) -> None:
        mailbox.mock(return_value=_settings_response(_reply_payload(external_audience=audience)))

        answer = await settings_tool.get_mailbox_settings(client, include="replies")

        assert answer.automatic_reply is not None
        assert answer.automatic_reply.external_audience == audience

    async def test_a_mailbox_graph_reported_no_reply_setting_for_is_still_answered(
        self, client: GraphServiceClient, mailbox: respx.Route
    ) -> None:
        mailbox.mock(return_value=_settings_response(None))

        answer = await settings_tool.get_mailbox_settings(client, include="replies")

        assert answer.automatic_reply is not None
        assert answer.automatic_reply.status is None
        assert answer.automatic_reply.internal_reply_message is None
        assert answer.automatic_reply.scheduled_start is None


class TestThePreferences:
    @pytest.mark.parametrize("zone", ["W. Europe Standard Time", "Europe/Zurich"])
    async def test_the_time_zone_is_reported_in_the_spelling_graph_gave(
        self, client: GraphServiceClient, mailbox: respx.Route, zone: str
    ) -> None:
        mailbox.mock(return_value=_settings_response(None, _preferences_payload(time_zone=zone)))

        answer = await settings_tool.get_mailbox_settings(client, include="preferences")

        assert answer.time_zone == zone

    @pytest.mark.usefixtures("mailbox")
    async def test_the_working_hours_carry_the_days_the_times_and_the_zone(
        self, client: GraphServiceClient
    ) -> None:
        answer = await settings_tool.get_mailbox_settings(client, include="preferences")

        hours = answer.working_hours
        assert hours is not None
        assert hours.days == ["monday", "tuesday", "wednesday", "thursday", "friday"]
        assert hours.starts_at == "08:00:00"
        assert hours.ends_at == "17:00:00"
        assert hours.time_zone == "W. Europe Standard Time"

    @pytest.mark.usefixtures("mailbox")
    async def test_the_language_carries_the_locale_and_its_display_name(
        self, client: GraphServiceClient
    ) -> None:
        answer = await settings_tool.get_mailbox_settings(client, include="preferences")

        assert answer.language is not None
        assert answer.language.locale == "de-CH"
        assert answer.language.display_name == "German (Switzerland)"

    async def test_a_language_with_only_a_locale_has_a_null_display_name(
        self, client: GraphServiceClient, mailbox: respx.Route
    ) -> None:
        mailbox.mock(
            return_value=_settings_response(
                None, {**_preferences_payload(), "language": {"locale": "fr-CH"}}
            )
        )

        answer = await settings_tool.get_mailbox_settings(client, include="preferences")

        assert answer.language is not None
        assert answer.language.locale == "fr-CH"
        assert answer.language.display_name is None

    @pytest.mark.usefixtures("mailbox")
    async def test_the_archive_folder_is_a_folder_handle_that_outlook_move_mail_takes(
        self, client: GraphServiceClient
    ) -> None:
        answer = await settings_tool.get_mailbox_settings(client, include="preferences")

        assert answer.archive_folder_uri == MailFolderHandle(_ARCHIVE_FOLDER_ID).uri
        assert mail_folder_handle(answer.archive_folder_uri or "") == MailFolderHandle(
            _ARCHIVE_FOLDER_ID
        )

    @pytest.mark.parametrize("archive_folder", [None, ""])
    async def test_a_mailbox_with_no_archive_folder_has_a_null_handle(
        self, client: GraphServiceClient, mailbox: respx.Route, archive_folder: str | None
    ) -> None:
        mailbox.mock(
            return_value=_settings_response(
                None, _preferences_payload(archive_folder=archive_folder)
            )
        )

        answer = await settings_tool.get_mailbox_settings(client, include="preferences")

        assert answer.archive_folder_uri is None

    async def test_a_mailbox_graph_reported_no_preferences_for_is_still_answered(
        self, client: GraphServiceClient, mailbox: respx.Route
    ) -> None:
        mailbox.mock(return_value=_settings_response(None))

        answer = await settings_tool.get_mailbox_settings(client, include="preferences")

        assert [getattr(answer, name) for name in _PREFERENCE_PARTS] == [None] * 4

    @pytest.mark.usefixtures("rules", "mailbox", "categories")
    async def test_the_default_answers_the_reply_and_the_preferences_from_one_response(
        self, client: GraphServiceClient
    ) -> None:
        answer = await settings_tool.get_mailbox_settings(client, include="all")

        assert answer.automatic_reply is not None
        assert answer.automatic_reply.status == "scheduled"
        assert answer.time_zone == "W. Europe Standard Time"
        assert answer.archive_folder_uri == MailFolderHandle(_ARCHIVE_FOLDER_ID).uri


class TestCategories:
    async def test_it_answers_the_names_the_user_chose(
        self, client: GraphServiceClient, categories: respx.Route
    ) -> None:
        categories.mock(
            return_value=_page(
                {"displayName": "Follow up", "color": "preset0"},
                {"displayName": "Confidential", "color": "preset4"},
            )
        )

        answer = await settings_tool.get_mailbox_settings(client, include="categories")

        assert answer.categories == ["Follow up", "Confidential"]

    @pytest.mark.usefixtures("categories")
    async def test_a_mailbox_with_no_categories_answers_an_empty_list(
        self, client: GraphServiceClient
    ) -> None:
        answer = await settings_tool.get_mailbox_settings(client, include="categories")

        assert answer.categories == []
        assert answer.categories_capped is False


class TestWhatIncludeLeavesOut:
    @pytest.mark.parametrize(
        ("include", "present"),
        [
            ("rules", ("rules",)),
            ("replies", ("automatic_reply",)),
            ("categories", ("categories",)),
            ("preferences", _PREFERENCE_PARTS),
        ],
    )
    @pytest.mark.usefixtures("rules", "mailbox", "categories")
    async def test_what_was_not_asked_for_is_null_rather_than_empty(
        self, client: GraphServiceClient, include: settings_tool.Include, present: tuple[str, ...]
    ) -> None:
        answer = await settings_tool.get_mailbox_settings(client, include=include)

        answered = {
            name: getattr(answer, name) is not None
            for name in ("rules", "automatic_reply", "categories", *_PREFERENCE_PARTS)
        }
        assert answered == {name: (name in present) for name in answered}

    @pytest.mark.usefixtures("mailbox")
    async def test_a_cap_flag_is_null_for_a_collection_that_was_not_read(
        self, client: GraphServiceClient
    ) -> None:
        answer = await settings_tool.get_mailbox_settings(client, include="replies")

        assert answer.rules_capped is None
        assert answer.categories_capped is None


class TestWhatItCannotSee:
    @pytest.mark.parametrize("include", ["all", "rules", "replies", "categories", "preferences"])
    @pytest.mark.usefixtures("rules", "mailbox", "categories")
    async def test_every_answer_says_mailbox_level_forwarding_is_not_covered(
        self, client: GraphServiceClient, include: settings_tool.Include
    ) -> None:
        answer = await settings_tool.get_mailbox_settings(client, include=include)

        assert answer.covers_mailbox_level_forwarding is False

    def test_the_field_says_a_clean_rule_list_is_not_a_forwarding_free_mailbox(self) -> None:
        field = settings_tool.MailboxSettingsReport.model_fields["covers_mailbox_level_forwarding"]

        assert field.description is not None
        assert "Exchange mailbox-level forwarding" in field.description
        assert "does not prove" in field.description
        assert "nobody forwards this mailbox's mail" in field.description

    def test_the_tool_description_names_the_blind_spot_too(self) -> None:
        description = settings_tool._DESCRIPTION  # pyright: ignore[reportPrivateUsage]

        assert "cannot see Exchange mailbox-level forwarding" in description
        assert "does not prove that nobody forwards this mailbox's mail" in description


class TestWhatItPublishes:
    def test_every_field_of_the_answer_says_what_it_is(self, published: Tool) -> None:
        undescribed = sorted(path for path, text in _described(published).items() if not text)

        assert undescribed == [], "a model is handed these values with nothing to say what they are"

    @pytest.mark.parametrize(
        "path",
        [
            "answer.rules",
            "answer.time_zone",
            "answer.working_hours",
            "answer.language",
            "answer.archive_folder_uri",
            "Language.locale",
            "Language.display_name",
        ],
    )
    def test_every_new_field_says_what_it_is_in_15_to_60_words(
        self, published: Tool, path: str
    ) -> None:
        description = _described(published)[path] or ""

        assert 15 <= len(description.split()) <= 60

    def test_the_archive_folder_field_names_the_tool_that_takes_the_handle(
        self, published: Tool
    ) -> None:
        text = _described(published)["answer.archive_folder_uri"] or ""

        assert "outlook_move_mail" in text
        assert "`folder_ref`" in text

    def test_the_time_zone_field_claims_only_what_microsoft_365_reports(
        self, published: Tool
    ) -> None:
        text = _described(published)["answer.time_zone"] or ""

        assert "as Microsoft 365 reports it" in text
        assert "administrator" not in text

    def test_a_rule_predicate_that_is_not_set_is_not_a_required_key(self, published: Tool) -> None:
        answer = cast("Mapping[str, object]", published.output_schema)
        definitions = cast("Mapping[str, Mapping[str, object]]", answer["$defs"])

        assert "required" not in definitions["RuleConditions"]
        assert "required" not in definitions["RuleActions"]
        assert "required" not in definitions["SizeRangeKb"]

    def test_a_rule_is_published_in_the_one_shape_that_the_rule_tools_answer_with(
        self, published: Tool
    ) -> None:
        answer = cast("Mapping[str, object]", published.output_schema)
        definitions = cast("Mapping[str, Mapping[str, object]]", answer["$defs"])

        assert "InboxRule" not in definitions
        assert set(cast("Mapping[str, object]", definitions["MailRule"]["properties"])) == set(
            MailRule.model_fields
        )

    def test_the_include_field_names_the_preferences_part(self, published: Tool) -> None:
        properties = cast("Mapping[str, Mapping[str, object]]", published.parameters["properties"])
        text = cast("str", properties["include"]["description"])

        assert "`preferences`" in text
        assert "the time zone, the working hours, the language, and the archive folder" in text

    def test_the_description_names_every_part_of_the_answer(self, published: Tool) -> None:
        description = published.description or ""

        for part in (
            "inbox rules with their conditions, exceptions, and actions",
            "the automatic reply",
            "the category names",
            "the time zone",
            "the working hours",
            "the language",
            "the archive folder",
        ):
            assert part in description

    def test_the_description_keeps_the_house_shape(self, published: Tool) -> None:
        description = published.description or ""

        lead, separator, notes = description.partition("\n\nNotes:\n")
        assert separator, "a lead paragraph, a blank line, then Notes:"
        assert "\n" not in lead.strip()
        assert 1 <= sum(line.startswith("- ") for line in notes.splitlines()) <= 4
        assert 45 <= len(description.split()) <= 210


class TestPaging:
    async def test_the_pages_of_the_rule_listing_are_followed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_RULES, params={"$skiptoken": "second"}).mock(
            return_value=_page(
                _rule_payload(
                    _OTHER_RULE_ID,
                    display_name="Send to personal",
                    actions={"forwardTo": [_recipient(_OUTSIDE)]},
                )
            )
        )
        graph.get(_RULES).mock(
            return_value=_page(_rule_payload(), next_link=f"{GRAPH_V1}{_RULES}?$skiptoken=second")
        )

        answer = await settings_tool.get_mailbox_settings(client, include="rules")

        assert answer.rules is not None
        assert [rule.display_name for rule in answer.rules] == ["Newsletters", "Send to personal"]
        assert answer.rules_capped is False

    async def test_a_rule_listing_wider_than_the_scan_limit_says_it_was_capped(
        self,
        client: GraphServiceClient,
        rules: respx.Route,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings_tool, "MAX_SCANNED_ITEMS", 2)
        rules.mock(
            return_value=_page(*(_rule_payload(f"{_RULE_ID}-{number}") for number in range(3)))
        )

        answer = await settings_tool.get_mailbox_settings(client, include="rules")

        assert answer.rules is not None
        assert len(answer.rules) == 2
        assert answer.rules_capped is True


class TestGraphFailures:
    async def test_a_refusal_arrives_classified_for_the_tool_to_explain(
        self, client: GraphServiceClient, rules: respx.Route
    ) -> None:
        rules.mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await settings_tool.get_mailbox_settings(client, include="rules")

    def test_the_permission_is_the_one_microsoft_documents(self) -> None:
        assert settings_tool.GRAPH_PERMISSIONS == ("MailboxSettings.Read",)

    def test_the_steps_are_named_one_per_graph_call(self) -> None:
        assert settings_tool.STEP_SETTINGS == "mailbox_settings"
        assert settings_tool.STEP_RULES == "mail_rules"
        assert settings_tool.STEP_CATEGORIES == "mail_categories"

    def test_a_404_is_answered_as_a_mailbox_that_is_not_there(self) -> None:
        assert "takes no id" in settings_tool.GRAPH_NOT_FOUND
        assert "Exchange Online mailbox" in settings_tool.GRAPH_NOT_FOUND
