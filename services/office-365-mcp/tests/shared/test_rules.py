"""A rule's conditions and exceptions are one Graph type, `messageRulePredicates`, with thirty
optional members. Graph sends an unset member as null or as an empty list, so the assertions read
the serialized dump, which leaves an unset member out.
"""

import dataclasses

import pytest
from msgraph.generated.models.email_address import EmailAddress
from msgraph.generated.models.importance import Importance
from msgraph.generated.models.message_action_flag import MessageActionFlag
from msgraph.generated.models.message_rule import MessageRule
from msgraph.generated.models.message_rule_predicates import MessageRulePredicates
from msgraph.generated.models.recipient import Recipient
from msgraph.generated.models.sensitivity import Sensitivity
from msgraph.generated.models.size_range import SizeRange
from pydantic import BaseModel

from office_365_mcp.shared.handles import MailRuleHandle
from office_365_mcp.shared.rules import InboxRule, RuleConditions, SizeRangeKb, conditions_of

_RULE_ID = "AQAAAJSYNTHETIC-rule-one"

_STRING_LISTS = (
    "body_contains",
    "body_or_subject_contains",
    "categories",
    "header_contains",
    "recipient_contains",
    "sender_contains",
    "subject_contains",
)

_BOOLEANS = (
    "has_attachments",
    "is_approval_request",
    "is_automatic_forward",
    "is_automatic_reply",
    "is_encrypted",
    "is_meeting_request",
    "is_meeting_response",
    "is_non_delivery_report",
    "is_permission_controlled",
    "is_read_receipt",
    "is_signed",
    "is_voicemail",
    "not_sent_to_me",
    "sent_cc_me",
    "sent_only_to_me",
    "sent_to_me",
    "sent_to_or_cc_me",
)

_ADDRESS_LISTS = ("from_addresses", "sent_to_addresses")

_SDK_ONLY = frozenset({"backing_store", "additional_data", "odata_type"})


def _recipient(address: str | None, *, name: str | None = None) -> Recipient:
    return Recipient(email_address=EmailAddress(address=address, name=name))


def _predicates(**members: object) -> MessageRulePredicates:
    predicates = MessageRulePredicates()
    for name, value in members.items():
        setattr(predicates, name, value)
    return predicates


def _conditions(predicates: MessageRulePredicates) -> RuleConditions:
    conditions = conditions_of(predicates)
    assert conditions is not None
    return conditions


class TestEveryKindOfPredicate:
    @pytest.mark.parametrize("name", _STRING_LISTS)
    def test_a_list_of_strings_is_reported_under_its_own_name(self, name: str) -> None:
        conditions = _conditions(_predicates(**{name: ["one", "two"]}))

        assert conditions.model_dump() == {name: ["one", "two"]}

    @pytest.mark.parametrize("name", _BOOLEANS)
    def test_a_flag_is_reported_under_its_own_name(self, name: str) -> None:
        conditions = _conditions(_predicates(**{name: True}))

        assert conditions.model_dump() == {name: True}

    @pytest.mark.parametrize("name", _BOOLEANS)
    def test_a_flag_that_graph_set_to_false_is_reported_as_false(self, name: str) -> None:
        conditions = _conditions(_predicates(**{name: False}))

        assert conditions.model_dump() == {name: False}

    @pytest.mark.parametrize("name", _ADDRESS_LISTS)
    def test_addresses_are_reported_as_their_smtp_strings(self, name: str) -> None:
        conditions = _conditions(
            _predicates(**{name: [_recipient("ada@example.invalid", name="Ada")]})
        )

        assert conditions.model_dump() == {name: ["ada@example.invalid"]}

    @pytest.mark.parametrize("name", _ADDRESS_LISTS)
    def test_a_recipient_with_no_address_is_named_rather_than_dropped(self, name: str) -> None:
        conditions = _conditions(
            _predicates(
                **{
                    name: [
                        _recipient(None, name="Archive Service"),
                        _recipient("a@example.invalid"),
                    ]
                }
            )
        )

        assert conditions.model_dump() == {name: ["Archive Service", "a@example.invalid"]}

    @pytest.mark.parametrize(
        ("sent", "reported"),
        [(Importance.Low, "low"), (Importance.Normal, "normal"), (Importance.High, "high")],
    )
    def test_every_importance_is_reported_by_its_own_name(
        self, sent: Importance, reported: str
    ) -> None:
        conditions = _conditions(_predicates(importance=sent))

        assert conditions.model_dump() == {"importance": reported}

    @pytest.mark.parametrize(
        ("sent", "reported"),
        [
            (Sensitivity.Normal, "normal"),
            (Sensitivity.Personal, "personal"),
            (Sensitivity.Private, "private"),
            (Sensitivity.Confidential, "confidential"),
        ],
    )
    def test_every_sensitivity_is_reported_by_its_own_name(
        self, sent: Sensitivity, reported: str
    ) -> None:
        conditions = _conditions(_predicates(sensitivity=sent))

        assert conditions.model_dump() == {"sensitivity": reported}

    @pytest.mark.parametrize(
        ("sent", "reported"),
        [
            (MessageActionFlag.Any, "any"),
            (MessageActionFlag.Call, "call"),
            (MessageActionFlag.DoNotForward, "doNotForward"),
            (MessageActionFlag.FollowUp, "followUp"),
            (MessageActionFlag.Fyi, "fyi"),
            (MessageActionFlag.Forward, "forward"),
            (MessageActionFlag.NoResponseNecessary, "noResponseNecessary"),
            (MessageActionFlag.Read, "read"),
            (MessageActionFlag.Reply, "reply"),
            (MessageActionFlag.ReplyToAll, "replyToAll"),
            (MessageActionFlag.Review, "review"),
        ],
    )
    def test_every_action_flag_is_reported_by_its_own_name(
        self, sent: MessageActionFlag, reported: str
    ) -> None:
        conditions = _conditions(_predicates(message_action_flag=sent))

        assert conditions.model_dump() == {"message_action_flag": reported}

    @pytest.mark.parametrize(
        ("size", "reported"),
        [
            (SizeRange(minimum_size=100), {"minimum_kb": 100}),
            (SizeRange(maximum_size=2048), {"maximum_kb": 2048}),
            (
                SizeRange(minimum_size=100, maximum_size=2048),
                {"minimum_kb": 100, "maximum_kb": 2048},
            ),
        ],
    )
    def test_a_size_range_reports_only_the_bounds_it_sets(
        self, size: SizeRange, reported: dict[str, int]
    ) -> None:
        conditions = _conditions(_predicates(within_size_range=size))

        assert conditions.model_dump() == {"within_size_range": reported}

    def test_a_size_range_that_sets_no_bound_is_no_range(self) -> None:
        assert SizeRangeKb.from_size_range(SizeRange()) is None
        assert SizeRangeKb.from_size_range(None) is None


class TestWhatCountsAsNothingSet:
    def test_no_predicates_is_no_conditions(self) -> None:
        assert conditions_of(None) is None

    def test_a_predicates_object_with_nothing_in_it_is_no_conditions(self) -> None:
        assert conditions_of(MessageRulePredicates()) is None

    @pytest.mark.parametrize("name", [*_STRING_LISTS, *_ADDRESS_LISTS])
    def test_an_empty_list_is_not_a_predicate(self, name: str) -> None:
        nothing: list[str] = []

        assert conditions_of(_predicates(**{name: nothing})) is None

    def test_a_list_of_recipients_with_no_address_and_no_name_is_not_a_predicate(self) -> None:
        assert conditions_of(_predicates(from_addresses=[_recipient(None)])) is None

    def test_an_empty_size_range_is_not_a_predicate(self) -> None:
        assert conditions_of(_predicates(within_size_range=SizeRange())) is None


class TestOnlyWhatIsSetIsPublished:
    def test_the_unset_predicates_are_absent_from_the_dump_and_not_null(self) -> None:
        conditions = _conditions(
            _predicates(subject_contains=["invoice"], has_attachments=True, body_contains=[])
        )

        assert conditions.model_dump() == {"subject_contains": ["invoice"], "has_attachments": True}
        assert conditions.model_dump(mode="json") == conditions.model_dump()
        assert "null" not in conditions.model_dump_json()

    def test_the_unset_bound_of_a_size_range_is_absent_from_the_nested_dump(self) -> None:
        conditions = _conditions(_predicates(within_size_range=SizeRange(minimum_size=5)))

        assert conditions.model_dump_json() == '{"within_size_range":{"minimum_kb":5}}'

    def test_every_member_is_optional_in_the_schema(self) -> None:
        for model in (RuleConditions, SizeRangeKb):
            assert "required" not in model.model_json_schema(mode="serialization")


class TestTheModelCoversWhatMicrosoftDefines:
    def test_every_predicate_the_sdk_knows_has_a_field_and_no_field_is_invented(self) -> None:
        sdk = {field.name for field in dataclasses.fields(MessageRulePredicates)} - _SDK_ONLY

        assert set(RuleConditions.model_fields) == sdk

    def test_the_tests_name_every_kind_of_predicate_once(self) -> None:
        named = [
            *_STRING_LISTS,
            *_BOOLEANS,
            *_ADDRESS_LISTS,
            "importance",
            "sensitivity",
            "message_action_flag",
            "within_size_range",
        ]

        assert sorted(named) == sorted(RuleConditions.model_fields)

    @pytest.mark.parametrize(
        ("model", "name"),
        [
            (model, name)
            for model in (RuleConditions, SizeRangeKb, InboxRule)
            for name in model.model_fields
        ],
    )
    def test_every_field_says_what_it_is_in_15_to_60_words(
        self, model: type[BaseModel], name: str
    ) -> None:
        description = model.model_fields[name].description or ""

        assert 15 <= len(description.split()) <= 60


class TestAnInboxRule:
    def test_the_conditions_and_the_exceptions_are_read_from_their_own_members(self) -> None:
        rule = InboxRule.from_rule(
            MessageRule(
                id=_RULE_ID,
                conditions=_predicates(sender_contains=["newsletter"]),
                exceptions=_predicates(sent_to_me=True, categories=["Important"]),
            )
        )

        assert rule.conditions is not None
        assert rule.conditions.model_dump() == {"sender_contains": ["newsletter"]}
        assert rule.exceptions is not None
        assert rule.exceptions.model_dump() == {"sent_to_me": True, "categories": ["Important"]}

    def test_a_rule_with_no_conditions_and_no_exceptions_reports_both_as_null(self) -> None:
        rule = InboxRule.from_rule(MessageRule(id=_RULE_ID))

        assert rule.conditions is None
        assert rule.exceptions is None

    def test_a_rule_with_an_exception_and_no_condition_keeps_only_the_exception(self) -> None:
        rule = InboxRule.from_rule(
            MessageRule(id=_RULE_ID, exceptions=_predicates(is_automatic_reply=True))
        )

        assert rule.conditions is None
        assert rule.exceptions is not None
        assert rule.exceptions.is_automatic_reply is True

    def test_the_published_rule_nests_only_the_set_predicates(self) -> None:
        rule = InboxRule.from_rule(
            MessageRule(
                id=_RULE_ID,
                conditions=_predicates(subject_contains=["invoice"], body_contains=[]),
            )
        )

        published = rule.model_dump(mode="json")
        assert published["conditions"] == {"subject_contains": ["invoice"]}
        assert published["exceptions"] is None

    def test_the_handle_is_the_one_that_names_the_rule(self) -> None:
        assert InboxRule.from_rule(MessageRule(id=_RULE_ID)).uri == MailRuleHandle(_RULE_ID).uri

    def test_a_rule_with_no_id_is_refused(self) -> None:
        with pytest.raises(AssertionError, match="no id"):
            _ = InboxRule.from_rule(MessageRule())

    def test_a_rule_handle_names_the_tool_that_turns_the_rule_off(self) -> None:
        described = InboxRule.model_fields["uri"].description

        assert described is not None
        assert "outlook_disable_mail_rule" in described
        assert "no tool here can change" not in described
        assert "No tool here can delete a rule." in described
