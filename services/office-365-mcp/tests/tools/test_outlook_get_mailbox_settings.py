"""`outlook_get_mailbox_settings`: what it asks Graph for, what it reads out of a rule, and the one
thing it says it cannot see.

Every response body here is synthesised. None came from a real mailbox.
"""

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden
from office_365_mcp.shared.handles import MailRuleHandle
from office_365_mcp.tools import outlook_get_mailbox_settings as settings_tool

from .conftest import GRAPH_V1

_RULES = "/me/mailFolders/inbox/messageRules"
_SETTINGS = "/me/mailboxSettings"
_CATEGORIES = "/me/outlook/masterCategories"

_RULE_ID = "AQAAAJSYNTHETIC-rule-one"
_OTHER_RULE_ID = "AQAAAJSYNTHETIC-rule-two"
_ARCHIVE_FOLDER_ID = "AQMkADAwSYNTHETIC-archive"

_OUTSIDE = "collector@elsewhere.invalid"
_INSIDE = "deputy@example.invalid"


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
    actions: dict[str, object] | None = None,
) -> dict[str, object]:
    """`actions=None` is a rule Graph reported no actions object for at all."""
    payload: dict[str, object] = {
        "id": rule_id,
        "displayName": display_name,
        "isEnabled": is_enabled,
        "sequence": sequence,
        "isReadOnly": is_read_only,
        "hasError": has_error,
    }
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


def _page(*items: dict[str, object], next_link: str | None = None) -> httpx.Response:
    body: dict[str, object] = {"value": list(items)}
    if next_link is not None:
        body["@odata.nextLink"] = next_link
    return httpx.Response(200, json=body)


def _settings_response(reply: dict[str, object] | None) -> httpx.Response:
    """`reply=None` is a mailbox Graph answered with no `automaticRepliesSetting` on it."""
    body: dict[str, object] = {} if reply is None else {"automaticRepliesSetting": reply}
    return httpx.Response(200, json=body)


@pytest.fixture
def rules(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_RULES).mock(return_value=_page())


@pytest.fixture
def mailbox(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_SETTINGS).mock(return_value=_settings_response(_reply_payload()))


@pytest.fixture
def categories(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_CATEGORIES).mock(return_value=_page())


class TestWhatItAsksGraphFor:
    async def test_the_default_reads_all_three_collections(
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
        [("rules", _RULES), ("replies", _SETTINGS), ("categories", _CATEGORIES)],
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
        """The whole of what `include` is for: a caller asking about the automatic reply pays for
        the automatic reply and not for a rule listing and a category listing as well."""
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
        """Graph hangs `messageRules` off any folder and documents the collection as the Inbox's,
        so the locale-independent well-known name is the address rather than a folder handle."""
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
            "actions",
        ]
        assert params["$top"] == str(settings_tool.MAX_RULES)

    async def test_it_never_asks_for_the_conditions_it_does_not_report(
        self, client: GraphServiceClient, rules: respx.Route
    ) -> None:
        """This answers what a rule does, never which mail it does it to. Reading `conditions` and
        answering a summary of them would look like the answer to a question nobody asked."""
        _ = await settings_tool.get_mailbox_settings(client, include="rules")

        selected = rules.calls.last.request.url.params["$select"].split(",")
        assert "conditions" not in selected
        assert "exceptions" not in selected

    async def test_it_asks_the_mailbox_for_the_automatic_reply_alone(
        self, client: GraphServiceClient, mailbox: respx.Route
    ) -> None:
        """Microsoft documents `mailboxSettings` as needing `$select`, and the other eight
        properties — working hours, date format, time zone — are not what this tool reports."""
        _ = await settings_tool.get_mailbox_settings(client, include="replies")

        params = mailbox.calls.last.request.url.params
        assert params["$select"].split(",") == ["automaticRepliesSetting"]


class TestWhatARuleSays:
    async def test_a_forwarding_rule_names_the_addresses_it_forwards_to(
        self, client: GraphServiceClient, rules: respx.Route
    ) -> None:
        """The question this tool exists for: a named field, not something inferred from a blob."""
        rules.mock(
            return_value=_page(
                _rule_payload(
                    actions={"forwardTo": [_recipient(_OUTSIDE)], "stopProcessingRules": False}
                )
            )
        )

        answer = await settings_tool.get_mailbox_settings(client, include="rules")

        assert answer.rules is not None
        assert answer.rules[0].forwards_to == [_OUTSIDE]

    async def test_a_redirect_and_an_attachment_forward_are_reported_apart_from_a_forward(
        self, client: GraphServiceClient, rules: respx.Route
    ) -> None:
        """Three different ways mail leaves, and Outlook shows them as three different actions."""
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
        assert rule[0].forwards_to == [_OUTSIDE]
        assert rule[0].redirects_to == [_INSIDE]
        assert rule[0].forward_as_attachment_to == ["audit@example.invalid"]

    async def test_a_recipient_with_no_address_is_named_rather_than_dropped(
        self, client: GraphServiceClient, rules: respx.Route
    ) -> None:
        """A destination left out of the list is a destination the user never hears about, so the
        display name stands in when Graph recorded no address."""
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
        assert rule[0].forwards_to == ["Archive Service", _OUTSIDE]

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
        assert rule[0].moves_to_folder == _ARCHIVE_FOLDER_ID
        assert rule[0].deletes is True
        assert rule[0].marks_as_read is True
        assert rule[0].stops_processing_more_rules is True

    async def test_a_rule_that_permanently_deletes_is_reported_as_deleting(
        self, client: GraphServiceClient, rules: respx.Route
    ) -> None:
        """Graph spells destroying a message two ways, and a field that reported only `delete`
        would answer the sharper of the two with silence."""
        rules.mock(
            return_value=_page(_rule_payload(actions={"delete": False, "permanentDelete": True}))
        )

        rule = (await settings_tool.get_mailbox_settings(client, include="rules")).rules

        assert rule is not None
        assert rule[0].deletes is True

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
        assert rule[0].deletes is False
        assert rule[0].marks_as_read is False
        assert rule[0].forwards_to == []
        assert rule[0].moves_to_folder is None

    async def test_a_rule_graph_reported_no_actions_for_is_still_listed(
        self, client: GraphServiceClient, rules: respx.Route
    ) -> None:
        """ "Graph said nothing" is not "the rule does nothing", so every action reads null rather
        than false — and the rule is still in the list, because it exists."""
        rules.mock(return_value=_page(_rule_payload(actions=None)))

        rule = (await settings_tool.get_mailbox_settings(client, include="rules")).rules

        assert rule is not None
        assert rule[0].uri == MailRuleHandle(_RULE_ID).uri
        assert rule[0].deletes is None
        assert rule[0].marks_as_read is None
        assert rule[0].stops_processing_more_rules is None
        assert rule[0].moves_to_folder is None
        assert rule[0].forwards_to == []

    @pytest.mark.usefixtures("rules")
    async def test_a_mailbox_with_no_rules_answers_an_empty_list(
        self, client: GraphServiceClient
    ) -> None:
        answer = await settings_tool.get_mailbox_settings(client, include="rules")

        assert answer.rules == []
        assert answer.rules_capped is False


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
        """A schedule read in the wrong zone reports an expired reply as live."""
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
        """Null here would read as "replies were not asked for", which is a different answer. Asked
        for and unanswered is an object whose every field is null."""
        mailbox.mock(return_value=_settings_response(None))

        answer = await settings_tool.get_mailbox_settings(client, include="replies")

        assert answer.automatic_reply is not None
        assert answer.automatic_reply.status is None
        assert answer.automatic_reply.internal_reply_message is None
        assert answer.automatic_reply.scheduled_start is None


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
            ("rules", "rules"),
            ("replies", "automatic_reply"),
            ("categories", "categories"),
        ],
    )
    @pytest.mark.usefixtures("rules", "mailbox", "categories")
    async def test_what_was_not_asked_for_is_null_rather_than_empty(
        self, client: GraphServiceClient, include: settings_tool.Include, present: str
    ) -> None:
        """An empty list reads as "there are none", which is a claim this call never made."""
        answer = await settings_tool.get_mailbox_settings(client, include=include)

        answered = {
            name: getattr(answer, name) is not None
            for name in ("rules", "automatic_reply", "categories")
        }
        assert answered == {name: (name == present) for name in answered}

    @pytest.mark.usefixtures("mailbox")
    async def test_a_cap_flag_is_null_for_a_collection_that_was_not_read(
        self, client: GraphServiceClient
    ) -> None:
        answer = await settings_tool.get_mailbox_settings(client, include="replies")

        assert answer.rules_capped is None
        assert answer.categories_capped is None


class TestWhatItCannotSee:
    @pytest.mark.parametrize("include", ["all", "rules", "replies", "categories"])
    @pytest.mark.usefixtures("rules", "mailbox", "categories")
    async def test_every_answer_says_mailbox_level_forwarding_is_not_covered(
        self, client: GraphServiceClient, include: settings_tool.Include
    ) -> None:
        """A constant field and not a caveat in prose: the caller that most needs it is the one
        reading an empty rule list, and prose is what a model drops first."""
        answer = await settings_tool.get_mailbox_settings(client, include=include)

        assert answer.covers_mailbox_level_forwarding is False

    def test_the_field_says_a_clean_rule_list_is_not_a_forwarding_free_mailbox(self) -> None:
        """The sharpest sentence in the tool, and the one a confident wrong answer comes from."""
        field = settings_tool.MailboxSettingsReport.model_fields["covers_mailbox_level_forwarding"]

        assert field.description is not None
        assert "Set-Mailbox -ForwardingSmtpAddress" in field.description
        assert "is NOT" in field.description
        assert "not being forwarded" in field.description

    def test_the_tool_description_names_the_blind_spot_too(self) -> None:
        """A caller choosing this tool reads the description before any field, so the limit is
        stated where the choice is made as well as where the answer arrives."""
        description = settings_tool._DESCRIPTION  # pyright: ignore[reportPrivateUsage]

        assert "CANNOT see Exchange mailbox-level forwarding" in description
        assert 'never "this mailbox is not being forwarded"' in description


class TestPaging:
    async def test_the_pages_of_the_rule_listing_are_followed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """A rule on page two is a rule that forwards mail, so reading only the first page would
        answer "nothing forwards your mail" from half the evidence.

        The cursor route is registered before the bare one, which respx matches in registration
        order: the bare path matches a `$skiptoken` request too and would answer every page.
        """
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

    async def test_a_rule_listing_wider_than_the_bound_says_it_was_capped(
        self, client: GraphServiceClient, rules: respx.Route
    ) -> None:
        """A truncated rule list is the one truncation that matters here, so it is reported rather
        than left for the caller to notice."""
        rules.mock(
            return_value=_page(
                *(
                    _rule_payload(f"{_RULE_ID}-{number}")
                    for number in range(settings_tool.MAX_RULES + 1)
                )
            )
        )

        answer = await settings_tool.get_mailbox_settings(client, include="rules")

        assert answer.rules is not None
        assert len(answer.rules) == settings_tool.MAX_RULES
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
        """One permission covers all three collections, and it is new to this service."""
        assert settings_tool.GRAPH_PERMISSIONS == ("MailboxSettings.Read",)

    def test_the_steps_are_named_one_per_graph_call(self) -> None:
        assert settings_tool.STEP_SETTINGS == "mailbox_settings"
        assert settings_tool.STEP_RULES == "mail_rules"
        assert settings_tool.STEP_CATEGORIES == "mail_categories"

    def test_a_404_is_answered_as_a_mailbox_that_is_not_there(self) -> None:
        """The default advice — check the id came from a tool response — cannot apply: this tool
        takes no id, so nothing about the arguments could have caused it."""
        assert "takes no id" in settings_tool.GRAPH_NOT_FOUND
        assert "Exchange Online mailbox" in settings_tool.GRAPH_NOT_FOUND
