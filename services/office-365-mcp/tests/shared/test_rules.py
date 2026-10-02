"""A rule's conditions and exceptions are one Graph type, `messageRulePredicates`, with thirty
optional members. Graph sends an unset member as null or as an empty list, so the assertions read
the serialized dump, which leaves an unset member out.
"""

import dataclasses
import hashlib
import json
from collections.abc import Mapping
from typing import cast

import pytest
from msgraph.generated.models.email_address import EmailAddress
from msgraph.generated.models.importance import Importance
from msgraph.generated.models.message_action_flag import MessageActionFlag
from msgraph.generated.models.message_rule import MessageRule
from msgraph.generated.models.message_rule_actions import MessageRuleActions
from msgraph.generated.models.message_rule_predicates import MessageRulePredicates
from msgraph.generated.models.recipient import Recipient
from msgraph.generated.models.sensitivity import Sensitivity
from msgraph.generated.models.size_range import SizeRange
from pydantic import BaseModel

from office_365_mcp.shared.categories import LIST_CATEGORIES_GUARD
from office_365_mcp.shared.handles import MailFolderHandle, MailMessageHandle, MailRuleHandle
from office_365_mcp.shared.rules import (
    InboxRule,
    MailRule,
    RuleActions,
    RuleActionsInput,
    RuleConditions,
    RuleConditionsInput,
    RuleFolders,
    SizeRangeKb,
    actions_for,
    actions_of,
    conditions_of,
    forwarding_question,
    predicates_for,
    rule_confirmation_id,
    unusable_addresses,
    unusable_folders,
)

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
            for model in (
                RuleConditions,
                SizeRangeKb,
                InboxRule,
                RuleActions,
                MailRule,
                RuleConditionsInput,
                RuleActionsInput,
            )
            for name in model.model_fields
        ],
    )
    def test_every_field_says_what_it_is_in_15_to_60_words(
        self, model: type[BaseModel], name: str
    ) -> None:
        description = model.model_fields[name].description or ""

        assert 15 <= len(description.split()) <= 60

    @pytest.mark.parametrize(
        ("model", "name"),
        [(RuleConditionsInput, "categories"), (RuleActionsInput, "assign_categories")],
    )
    def test_a_category_field_promises_the_lister_only_where_it_exists(
        self, model: type[BaseModel], name: str
    ) -> None:
        description = model.model_fields[name].description or ""

        assert LIST_CATEGORIES_GUARD in description
        assert "outlook_list_categories" not in description.replace(LIST_CATEGORIES_GUARD, "")


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

    def test_a_rule_handle_names_the_tools_that_change_delete_and_turn_off_the_rule(self) -> None:
        described = InboxRule.model_fields["uri"].description

        assert described is not None
        assert "outlook_disable_mail_rule" in described
        assert "outlook_update_mail_rule" in described
        assert "outlook_delete_mail_rule" in described
        assert "no tool here can change" not in described
        assert "Pass it as `rule_ref`" in described


_ADA = "ada@example.invalid"
_DANA = "dana@example.invalid"
_ERIN = "erin@example.invalid"
_TEAM = "team@example.invalid"

_EVERY_CONDITION = RuleConditionsInput.model_validate(
    {
        **{name: ["one"] for name in _STRING_LISTS},
        **dict.fromkeys(_BOOLEANS, True),
        "from_addresses": [_ADA],
        "sent_to_addresses": [_TEAM],
        "importance": "high",
        "sensitivity": "private",
        "message_action_flag": "followUp",
        "within_size_range": {"minimum_kb": 1, "maximum_kb": 2048},
    }
)

_MOVED_INTO = "AQMkADAwSYNTHETIC-moved"
_COPIED_INTO = "AQMkADAwSYNTHETIC-copied"

_EVERY_ACTION = RuleActionsInput(
    assign_categories=["Newsletters"],
    copy_to_folder="archive",
    delete=True,
    forward_as_attachment_to=[_ADA],
    forward_to=[_DANA],
    mark_as_read=True,
    mark_importance="low",
    move_to_folder=MailFolderHandle(_MOVED_INTO).uri,
    redirect_to=[_ERIN],
    stop_processing_rules=True,
)

_FOLDERS = RuleFolders(move_to_folder=_MOVED_INTO, copy_to_folder=_COPIED_INTO, hidden=False)


def _property_names(schema: object) -> set[str]:
    if isinstance(schema, Mapping):
        mapping = cast("Mapping[str, object]", schema)
        named = set(cast("Mapping[str, object]", mapping.get("properties", {})))
        return named.union(*(_property_names(value) for value in mapping.values()))
    if isinstance(schema, list):
        return set[str]().union(*(_property_names(item) for item in cast("list[object]", schema)))
    return set()


class TestTheInputSpellsWhatTheAnswerReports:
    def test_every_predicate_the_answer_reports_can_be_given(self) -> None:
        assert set(RuleConditionsInput.model_fields) == set(RuleConditions.model_fields)

    def test_every_action_the_sdk_knows_is_reported_and_no_field_is_invented(self) -> None:
        sdk = {field.name for field in dataclasses.fields(MessageRuleActions)} - _SDK_ONLY

        assert set(RuleActions.model_fields) == sdk

    def test_every_reported_action_but_the_permanent_erase_can_be_given(self) -> None:
        assert set(RuleActionsInput.model_fields) == set(RuleActions.model_fields) - {
            "permanent_delete"
        }

    def test_no_input_schema_has_a_property_that_erases_permanently(self) -> None:
        for model in (RuleActionsInput, RuleConditionsInput):
            named = _property_names(model.model_json_schema())

            assert named
            assert not [name for name in named if "permanent" in name]

    def test_every_member_of_the_new_models_is_optional_in_the_schema(self) -> None:
        for model in (RuleActions, RuleConditionsInput, RuleActionsInput):
            assert "required" not in model.model_json_schema(mode="serialization")


class TestTheConditionsThatReachGraph:
    def test_every_predicate_given_comes_back_as_the_same_predicate(self) -> None:
        predicates = predicates_for(_EVERY_CONDITION)

        reported = conditions_of(predicates)
        assert reported is not None
        assert reported.model_dump() == _EVERY_CONDITION.model_dump(exclude_none=True)

    def test_an_address_reaches_graph_as_a_recipient_without_the_space_around_it(self) -> None:
        predicates = predicates_for(RuleConditionsInput(from_addresses=[f"  {_ADA} "]))

        assert predicates is not None
        assert predicates.from_addresses is not None
        email = predicates.from_addresses[0].email_address
        assert email is not None
        assert email.address == _ADA
        assert email.name is None

    def test_no_conditions_is_no_predicates(self) -> None:
        assert predicates_for(None) is None

    def test_a_conditions_object_that_sets_nothing_is_no_predicates(self) -> None:
        assert predicates_for(RuleConditionsInput()) is None
        assert predicates_for(RuleConditionsInput(within_size_range=SizeRangeKb())) is None


class TestTheActionsThatReachGraph:
    def test_every_action_given_comes_back_with_the_folder_ids_that_were_read(self) -> None:
        reported = actions_of(actions_for(_EVERY_ACTION, _FOLDERS))

        assert reported is not None
        assert reported.model_dump() == {
            **_EVERY_ACTION.model_dump(exclude_none=True),
            "move_to_folder": _MOVED_INTO,
            "copy_to_folder": _COPIED_INTO,
        }

    def test_no_action_ever_erases_permanently(self) -> None:
        assert actions_for(_EVERY_ACTION, _FOLDERS).permanent_delete is None

    def test_a_permanent_erase_smuggled_into_the_input_is_dropped(self) -> None:
        smuggled = RuleActionsInput.model_validate({"permanent_delete": True, "mark_as_read": True})

        assert actions_for(smuggled, _FOLDERS).permanent_delete is None
        assert RuleActionsInput.model_validate({"permanent_delete": True}).sets_nothing

    def test_an_actions_object_that_sets_something_says_so(self) -> None:
        assert RuleActionsInput().sets_nothing
        assert not RuleActionsInput(stop_processing_rules=True).sets_nothing


class TestTheActionsThatAreReported:
    def test_a_rule_that_already_erases_permanently_says_so(self) -> None:
        reported = actions_of(MessageRuleActions(permanent_delete=True))

        assert reported is not None
        assert reported.model_dump() == {"permanent_delete": True}

    def test_no_actions_and_empty_actions_are_both_no_actions(self) -> None:
        assert actions_of(None) is None
        assert actions_of(MessageRuleActions(forward_to=[], assign_categories=[])) is None

    def test_the_unset_actions_are_absent_from_the_dump_and_not_null(self) -> None:
        reported = actions_of(MessageRuleActions(mark_as_read=True, move_to_folder=_MOVED_INTO))

        assert reported is not None
        assert "null" not in reported.model_dump_json()


class TestAMailRule:
    def test_the_answer_nests_the_conditions_and_the_actions_the_rule_sets(self) -> None:
        rule = MailRule.from_rule(
            MessageRule(
                id=_RULE_ID,
                display_name="Newsletters",
                conditions=_predicates(sender_contains=["newsletter"]),
                actions=MessageRuleActions(mark_as_read=True),
            )
        )

        assert rule.uri == MailRuleHandle(_RULE_ID).uri
        assert rule.conditions is not None
        assert rule.conditions.model_dump() == {"sender_contains": ["newsletter"]}
        assert rule.actions is not None
        assert rule.actions.model_dump() == {"mark_as_read": True}
        assert rule.exceptions is None

    def test_a_rule_with_no_id_is_refused(self) -> None:
        with pytest.raises(AssertionError, match="no id"):
            _ = MailRule.from_rule(MessageRule())


class TestWhatAnInputMustSpell:
    @pytest.mark.parametrize(
        "entry",
        [
            "Dana Swope <dana@example.invalid>",
            "dana@example.invalid, erin@example.invalid",
            "Dana Swope",
            " ",
        ],
        ids=["display-name", "two-in-one", "name-only", "blank"],
    )
    def test_an_entry_that_is_not_one_address_is_named(self, entry: str) -> None:
        assert unusable_addresses(RuleActionsInput(forward_to=[entry])) == [entry]

    def test_every_address_of_every_part_is_read(self) -> None:
        found = unusable_addresses(
            RuleConditionsInput(from_addresses=["Ada"]),
            RuleConditionsInput(sent_to_addresses=["Team"]),
            RuleActionsInput(redirect_to=["Erin"], forward_as_attachment_to=[f" {_ADA} "]),
            None,
        )

        assert found == ["Ada", "Team", "Erin"]

    @pytest.mark.parametrize(
        "ref",
        ["archive", "deleteditems", "inbox", MailFolderHandle(_MOVED_INTO).uri],
    )
    def test_a_well_known_name_or_a_folder_handle_is_a_folder(self, ref: str) -> None:
        assert unusable_folders(RuleActionsInput(move_to_folder=ref, copy_to_folder=ref)) == []

    @pytest.mark.parametrize(
        "ref",
        [
            "Archive",
            "Newsletters",
            MailMessageHandle("AAMkAGI2SYNTHETIC-immutable-0001=").uri,
            "outlook:///folders/",
            _MOVED_INTO,
        ],
    )
    def test_anything_else_is_not_a_folder(self, ref: str) -> None:
        assert unusable_folders(RuleActionsInput(copy_to_folder=ref)) == [ref]
        assert unusable_folders(None) == []


class TestTheQuestionAboutMailThatLeaves:
    def test_a_rule_that_sends_nothing_on_is_no_question(self) -> None:
        actions = MessageRuleActions(mark_as_read=True, delete=True)

        assert forwarding_question("Create", "Newsletters", actions, None) is None
        assert forwarding_question("Create", "Newsletters", None, None) is None

    def test_the_question_names_every_address_with_what_the_rule_sends_to_it(self) -> None:
        question = forwarding_question(
            "Create",
            "Partner",
            MessageRuleActions(
                forward_to=[_recipient(_DANA), _recipient(_ERIN)],
                forward_as_attachment_to=[_recipient(_ADA)],
                redirect_to=[_recipient(_TEAM)],
            ),
            _predicates(sender_contains=["partner"]),
        )

        assert question is not None
        assert question.startswith("Create the inbox rule 'Partner'? Outlook forwards a copy")
        assert f"a copy of each matching message to {_DANA} and {_ERIN}. " in question
        assert f"each matching message as an attachment to {_ADA}. " in question
        assert f"Outlook redirects each matching message to {_TEAM}. " in question
        assert "acts only on the incoming messages that match its conditions" in question
        assert "cannot recall a message that the rule sends" in question

    def test_a_rule_with_no_condition_says_that_it_acts_on_every_message(self) -> None:
        question = forwarding_question(
            "Change", "All mail", MessageRuleActions(redirect_to=[_recipient(_TEAM)]), None
        )

        assert question is not None
        assert "it acts on every incoming message" in question


class TestTheAgreementBinding:
    def test_the_same_parts_give_the_same_id(self) -> None:
        first = rule_confirmation_id("tool", 1, True, _EVERY_ACTION, None)
        second = rule_confirmation_id("tool", 1, True, _EVERY_ACTION.model_copy(), None)

        assert first == second

    def test_a_change_of_any_part_gives_another_id(self) -> None:
        bound = {
            rule_confirmation_id("tool", 1, True, _EVERY_ACTION),
            rule_confirmation_id("tool", 2, True, _EVERY_ACTION),
            rule_confirmation_id("tool", 1, False, _EVERY_ACTION),
            rule_confirmation_id("tool", 1, True, RuleActionsInput(forward_to=[_ERIN])),
            rule_confirmation_id("other", 1, True, _EVERY_ACTION),
        }

        assert len(bound) == 5

    def test_the_id_is_a_sha256_of_the_canonical_parts(self) -> None:
        canonical = json.dumps(["tool", {"mark_as_read": True}], sort_keys=True)

        assert rule_confirmation_id("tool", RuleActionsInput(mark_as_read=True)) == (
            hashlib.sha256(canonical.encode()).hexdigest()
        )
