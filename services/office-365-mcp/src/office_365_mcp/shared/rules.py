import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Literal, Self, cast, get_args

from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.email_address import EmailAddress
from msgraph.generated.models.importance import Importance
from msgraph.generated.models.mail_folder import MailFolder
from msgraph.generated.models.message_action_flag import MessageActionFlag
from msgraph.generated.models.message_rule import MessageRule
from msgraph.generated.models.message_rule_actions import MessageRuleActions
from msgraph.generated.models.message_rule_predicates import MessageRulePredicates
from msgraph.generated.models.recipient import Recipient
from msgraph.generated.models.sensitivity import Sensitivity
from msgraph.generated.models.size_range import SizeRange
from msgraph.generated.users.item.mail_folders.item.mail_folder_item_request_builder import (
    MailFolderItemRequestBuilder,
)
from msgraph.generated.users.item.mail_folders.item.message_rules.item.message_rule_item_request_builder import (  # noqa: E501
    MessageRuleItemRequestBuilder,
)
from msgraph.generated.users.item.mail_folders.item.message_rules.message_rules_request_builder import (  # noqa: E501
    MessageRulesRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_step
from office_365_mcp.shared.handles import MailRuleHandle, mail_folder_handle
from office_365_mcp.shared.mail import ONE_ADDRESS, WellKnownFolder
from office_365_mcp.shared.odata import spelled
from office_365_mcp.shared.prose import cut_for_a_question

STEP_READ_RULE = "read_mail_rule"
STEP_RULE_FOLDER = "rule_folder"

RULE_FIELDS: tuple[str, ...] = (
    "id",
    "displayName",
    "isEnabled",
    "sequence",
    "isReadOnly",
    "hasError",
    "conditions",
    "exceptions",
    "actions",
)

_INBOX = "inbox"

_FOLDER_FIELDS: tuple[str, ...] = ("id", "displayName", "isHidden")

_WELL_KNOWN_FOLDERS: tuple[str, ...] = get_args(cast("object", WellKnownFolder.__value__))

_RuleQuery = MessageRuleItemRequestBuilder.MessageRuleItemRequestBuilderGetQueryParameters
_FolderQuery = MailFolderItemRequestBuilder.MailFolderItemRequestBuilderGetQueryParameters

type RuleImportance = Literal["low", "normal", "high"]
type RuleSensitivity = Literal["normal", "personal", "private", "confidential"]
type RuleActionFlag = Literal[
    "any",
    "call",
    "doNotForward",
    "followUp",
    "fyi",
    "forward",
    "noResponseNecessary",
    "read",
    "reply",
    "replyToAll",
    "review",
]

NOT_A_RULE_FOLDER = (
    "`move_to_folder` and `copy_to_folder` take a folder handle, outlook:///folders/{id}, exactly "
    + "as outlook_browse_folders reported it in `uri`. They also take a well-known folder name: "
    + "`inbox`, `sentitems`, `drafts`, `archive`, `deleteditems`, `junkemail`, or `clutter`. The "
    + "name of a folder that the user sees is not a handle. If you call this tool again with this "
    + "value, the call will fail the same way."
)

HIDDEN_RULE_FOLDER = (
    "That folder is hidden from the user in Outlook. A rule that moves or copies mail into it "
    + "hides that mail from the user. Use a folder that the user can see. outlook_browse_folders "
    + "lists them. If you call this tool again with this folder, the call will fail the same way."
)

NO_RULE_ACTION = (
    "`actions` sets no action. A rule must do at least one thing to each matching message, for "
    + "example `move_to_folder` or `mark_as_read`. Give at least one action and call again."
)

READ_ONLY_RULE = (
    "Microsoft 365 marks this rule as read-only. The rules API cannot change or delete a "
    + "read-only rule. A read-only rule still runs. Tell the user that this connector cannot "
    + "change or delete this rule. If you call this tool again with this handle, the call will "
    + "fail the same way."
)


def not_one_address(entries: Sequence[str]) -> str:
    listed = ", ".join(repr(entry) for entry in entries)
    return (
        "Each address in a rule must be one SMTP address, for example `ada@example.com`, and not "
        + f"a display name. These entries are not one address: {listed}. Use "
        + "outlook_find_recipient to find the address for a name that the user gave. Then call "
        + "again with that address."
    )


def _unset(value: object) -> bool:
    return value is None


class SizeRangeKb(BaseModel):
    minimum_kb: int | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "The minimum size, in kilobytes, that an incoming message must have for the "
            + "condition or the exception to apply. Absent when the range sets no minimum."
        ),
    )
    maximum_kb: int | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "The maximum size, in kilobytes, that an incoming message can have for the "
            + "condition or the exception to apply. Absent when the range sets no maximum."
        ),
    )

    @classmethod
    def from_size_range(cls, size_range: SizeRange | None) -> Self | None:
        if size_range is None or (
            size_range.minimum_size is None and size_range.maximum_size is None
        ):
            return None
        return cls(minimum_kb=size_range.minimum_size, maximum_kb=size_range.maximum_size)


class RuleConditions(BaseModel):
    body_contains: list[str] | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "The strings that the condition or the exception looks for in the body of an "
            + "incoming message."
        ),
    )
    body_or_subject_contains: list[str] | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "The strings that the condition or the exception looks for in the body or in the "
            + "subject of an incoming message."
        ),
    )
    categories: list[str] | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "The names of the categories that the condition or the exception looks for on an "
            + "incoming message."
        ),
    )
    from_addresses: list[str] | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "The sender addresses that the condition or the exception looks for on an incoming "
            + "message. Each entry is an SMTP address, or a display name when Graph gives no "
            + "address."
        ),
    )
    has_attachments: bool | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "True when an incoming message must have attachments for the condition or the "
            + "exception to apply."
        ),
    )
    header_contains: list[str] | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "The strings that the condition or the exception looks for in the headers of an "
            + "incoming message."
        ),
    )
    importance: str | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "The importance that an incoming message must carry for the condition or the "
            + "exception to apply: `low`, `normal`, or `high`."
        ),
    )
    is_approval_request: bool | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "True when an incoming message must be an approval request for the condition or the "
            + "exception to apply."
        ),
    )
    is_automatic_forward: bool | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "True when an incoming message must be an automatic forward for the condition or "
            + "the exception to apply."
        ),
    )
    is_automatic_reply: bool | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "True when an incoming message must be an automatic reply for the condition or the "
            + "exception to apply."
        ),
    )
    is_encrypted: bool | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "True when an incoming message must be encrypted for the condition or the exception "
            + "to apply."
        ),
    )
    is_meeting_request: bool | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "True when an incoming message must be a meeting request for the condition or the "
            + "exception to apply."
        ),
    )
    is_meeting_response: bool | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "True when an incoming message must be a meeting response for the condition or the "
            + "exception to apply."
        ),
    )
    is_non_delivery_report: bool | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "True when an incoming message must be a non-delivery report for the condition or "
            + "the exception to apply."
        ),
    )
    is_permission_controlled: bool | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "True when an incoming message must be permission controlled (RMS-protected) for the "
            + "condition or the exception to apply."
        ),
    )
    is_read_receipt: bool | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "True when an incoming message must be a read receipt for the condition or the "
            + "exception to apply."
        ),
    )
    is_signed: bool | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "True when an incoming message must be S/MIME-signed for the condition or the "
            + "exception to apply."
        ),
    )
    is_voicemail: bool | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "True when an incoming message must be a voice mail for the condition or the "
            + "exception to apply."
        ),
    )
    message_action_flag: str | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "The flag-for-action value that an incoming message must carry for the condition or "
            + "the exception to apply. The values are `any`, `call`, `doNotForward`, `followUp`, "
            + "`fyi`, `forward`, `noResponseNecessary`, `read`, `reply`, `replyToAll`, and "
            + "`review`."
        ),
    )
    not_sent_to_me: bool | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "True when the mailbox owner must not be a recipient of an incoming message for the "
            + "condition or the exception to apply."
        ),
    )
    recipient_contains: list[str] | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "The strings that the condition or the exception looks for in the To recipients or "
            + "in the Cc recipients of an incoming message."
        ),
    )
    sender_contains: list[str] | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "The strings that the condition or the exception looks for in the sender (`from`) "
            + "of an incoming message."
        ),
    )
    sensitivity: str | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "The sensitivity that an incoming message must carry for the condition or the "
            + "exception to apply: `normal`, `personal`, `private`, or `confidential`."
        ),
    )
    sent_cc_me: bool | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "True when the mailbox owner must be in the Cc recipients of an incoming message for "
            + "the condition or the exception to apply."
        ),
    )
    sent_only_to_me: bool | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "True when the mailbox owner must be the only recipient of an incoming message for "
            + "the condition or the exception to apply."
        ),
    )
    sent_to_addresses: list[str] | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "The recipient addresses that the condition or the exception looks for on an "
            + "incoming message. Each entry is an SMTP address, or a display name when Graph "
            + "gives no address."
        ),
    )
    sent_to_me: bool | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "True when the mailbox owner must be in the To recipients of an incoming message for "
            + "the condition or the exception to apply."
        ),
    )
    sent_to_or_cc_me: bool | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "True when the mailbox owner must be a To or Cc recipient of an incoming message for "
            + "the condition or the exception to apply."
        ),
    )
    subject_contains: list[str] | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "The strings that the condition or the exception looks for in the subject of an "
            + "incoming message."
        ),
    )
    within_size_range: SizeRangeKb | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "The range of sizes, in kilobytes, that an incoming message must fall in for the "
            + "condition or the exception to apply."
        ),
    )


def conditions_of(predicates: MessageRulePredicates | None) -> RuleConditions | None:
    if predicates is None:
        return None
    conditions = RuleConditions(
        body_contains=predicates.body_contains or None,
        body_or_subject_contains=predicates.body_or_subject_contains or None,
        categories=predicates.categories or None,
        from_addresses=_addresses(predicates.from_addresses) or None,
        has_attachments=predicates.has_attachments,
        header_contains=predicates.header_contains or None,
        importance=spelled(predicates.importance),
        is_approval_request=predicates.is_approval_request,
        is_automatic_forward=predicates.is_automatic_forward,
        is_automatic_reply=predicates.is_automatic_reply,
        is_encrypted=predicates.is_encrypted,
        is_meeting_request=predicates.is_meeting_request,
        is_meeting_response=predicates.is_meeting_response,
        is_non_delivery_report=predicates.is_non_delivery_report,
        is_permission_controlled=predicates.is_permission_controlled,
        is_read_receipt=predicates.is_read_receipt,
        is_signed=predicates.is_signed,
        is_voicemail=predicates.is_voicemail,
        message_action_flag=spelled(predicates.message_action_flag),
        not_sent_to_me=predicates.not_sent_to_me,
        recipient_contains=predicates.recipient_contains or None,
        sender_contains=predicates.sender_contains or None,
        sensitivity=spelled(predicates.sensitivity),
        sent_cc_me=predicates.sent_cc_me,
        sent_only_to_me=predicates.sent_only_to_me,
        sent_to_addresses=_addresses(predicates.sent_to_addresses) or None,
        sent_to_me=predicates.sent_to_me,
        sent_to_or_cc_me=predicates.sent_to_or_cc_me,
        subject_contains=predicates.subject_contains or None,
        within_size_range=SizeRangeKb.from_size_range(predicates.within_size_range),
    )
    return conditions if conditions.model_dump() else None


_RULE_URI = (
    "This is the handle of the rule, `outlook:///rules/{id}`. Pass it as `rule_ref` to "
    + "outlook_update_mail_rule, outlook_delete_mail_rule, or outlook_disable_mail_rule, if this "
    + "deployment exposes that tool."
)
_RULE_DISPLAY_NAME = (
    "The name of the rule. It is a label, and not a description of what the rule does. Null if "
    + "Graph recorded none."
)
_RULE_IS_ENABLED = (
    "True when the rule runs. False when the rule exists but does nothing now. Null if Graph does "
    + "not say."
)
_RULE_SEQUENCE = (
    "The position of the rule in the order in which Outlook runs the rules, lowest first. Null if "
    + "Graph does not say."
)
_RULE_IS_READ_ONLY = (
    "True for a rule that the rules API cannot change or delete. A read-only rule still runs. Null "
    + "if Graph does not say."
)
_RULE_HAS_ERROR = (
    "True when Microsoft 365 reports that the rule is in an error condition. Null if Graph does "
    + "not say."
)
_RULE_CONDITIONS = (
    "The conditions that trigger the actions of this rule. Only the predicates that the rule sets "
    + "appear. Null when Graph reports no condition."
)
_RULE_EXCEPTIONS = (
    "The exception conditions of this rule, in the same shape as `conditions`. Only the "
    + "predicates that the rule sets appear. Null when Graph reports no exception."
)


class InboxRule(BaseModel):
    uri: str = Field(description=_RULE_URI)
    display_name: str | None = Field(description=_RULE_DISPLAY_NAME)
    is_enabled: bool | None = Field(description=_RULE_IS_ENABLED)
    sequence: int | None = Field(description=_RULE_SEQUENCE)
    is_read_only: bool | None = Field(description=_RULE_IS_READ_ONLY)
    has_error: bool | None = Field(description=_RULE_HAS_ERROR)
    conditions: RuleConditions | None = Field(description=_RULE_CONDITIONS)
    exceptions: RuleConditions | None = Field(description=_RULE_EXCEPTIONS)
    forwards_to: list[str] = Field(
        description=(
            "The addresses to which this rule forwards a copy of each matching message. Empty "
            + "when the rule has no forward action."
        )
    )
    redirects_to: list[str] = Field(
        description=(
            "The addresses to which this rule redirects each matching message, with the original "
            + "sender kept. Empty when the rule has no redirect action."
        )
    )
    forward_as_attachment_to: list[str] = Field(
        description=(
            "The addresses to which this rule forwards each matching message as an attachment. "
            + "Empty when the rule has no such action."
        )
    )
    moves_to_folder: str | None = Field(
        description=(
            "The Graph id of the folder to which this rule moves each matching message. Null "
            + "when the rule does not move mail."
        )
    )
    deletes: bool | None = Field(
        description=(
            "True when the rule deletes each matching message, permanently or to Deleted Items. "
            + "Null when Graph reports no delete action."
        )
    )
    marks_as_read: bool | None = Field(
        description=(
            "True when the rule marks each matching message as read when it arrives. Null if "
            + "Graph does not say."
        )
    )
    stops_processing_more_rules: bool | None = Field(
        description=(
            "True when this rule stops Outlook from running any rule that comes after it in "
            + "`sequence`. Null if Graph does not say."
        )
    )

    @classmethod
    def from_rule(cls, rule: MessageRule) -> Self:
        assert rule.id is not None, "Graph returned a message rule with no id"
        actions = rule.actions
        return cls(
            uri=MailRuleHandle(rule.id).uri,
            display_name=rule.display_name,
            is_enabled=rule.is_enabled,
            sequence=rule.sequence,
            is_read_only=rule.is_read_only,
            has_error=rule.has_error,
            conditions=conditions_of(rule.conditions),
            exceptions=conditions_of(rule.exceptions),
            forwards_to=_addresses(None if actions is None else actions.forward_to),
            redirects_to=_addresses(None if actions is None else actions.redirect_to),
            forward_as_attachment_to=_addresses(
                None if actions is None else actions.forward_as_attachment_to
            ),
            moves_to_folder=None if actions is None else actions.move_to_folder,
            deletes=_deletes(actions),
            marks_as_read=None if actions is None else actions.mark_as_read,
            stops_processing_more_rules=(
                None if actions is None else actions.stop_processing_rules
            ),
        )


class RuleActions(BaseModel):
    assign_categories: list[str] | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "The names of the categories that the rule puts on each matching message. Absent when "
            + "the rule puts no category on the messages."
        ),
    )
    copy_to_folder: str | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "The Graph id of the folder in which the rule puts a copy of each matching message. "
            + "Absent when the rule copies no message."
        ),
    )
    delete: bool | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "True when the rule moves each matching message to Deleted Items. The user can move a "
            + "message back from there. Absent when the rule has no such action."
        ),
    )
    forward_as_attachment_to: list[str] | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "The addresses to which the rule forwards each matching message as an attachment. "
            + "Each entry is an SMTP address, or a display name when Graph gives no address."
        ),
    )
    forward_to: list[str] | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "The addresses to which the rule forwards a copy of each matching message. Each entry "
            + "is an SMTP address, or a display name when Graph gives no address."
        ),
    )
    mark_as_read: bool | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "True when the rule marks each matching message as read when it arrives. Absent when "
            + "the rule has no such action."
        ),
    )
    mark_importance: str | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "The importance that the rule sets on each matching message: `low`, `normal`, or "
            + "`high`. Absent when the rule sets no importance."
        ),
    )
    move_to_folder: str | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "The Graph id of the folder to which the rule moves each matching message. Absent "
            + "when the rule does not move mail."
        ),
    )
    permanent_delete: bool | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "True when the rule erases each matching message permanently, without Deleted Items. "
            + "No tool of this connector can add this action, but a rule can already have it."
        ),
    )
    redirect_to: list[str] | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "The addresses to which the rule redirects each matching message, with the original "
            + "sender kept. Each entry is an SMTP address, or a display name when Graph gives no "
            + "address."
        ),
    )
    stop_processing_rules: bool | None = Field(
        default=None,
        exclude_if=_unset,
        description=(
            "True when the rule stops Outlook from running the rules that come after it in "
            + "`sequence`. Absent when the rule has no such action."
        ),
    )


def actions_of(actions: MessageRuleActions | None) -> RuleActions | None:
    if actions is None:
        return None
    reported = RuleActions(
        assign_categories=actions.assign_categories or None,
        copy_to_folder=actions.copy_to_folder or None,
        delete=actions.delete,
        forward_as_attachment_to=_addresses(actions.forward_as_attachment_to) or None,
        forward_to=_addresses(actions.forward_to) or None,
        mark_as_read=actions.mark_as_read,
        mark_importance=spelled(actions.mark_importance),
        move_to_folder=actions.move_to_folder or None,
        permanent_delete=actions.permanent_delete,
        redirect_to=_addresses(actions.redirect_to) or None,
        stop_processing_rules=actions.stop_processing_rules,
    )
    return reported if reported.model_dump() else None


class MailRule(BaseModel):
    uri: str = Field(description=_RULE_URI)
    display_name: str | None = Field(description=_RULE_DISPLAY_NAME)
    is_enabled: bool | None = Field(description=_RULE_IS_ENABLED)
    sequence: int | None = Field(description=_RULE_SEQUENCE)
    is_read_only: bool | None = Field(description=_RULE_IS_READ_ONLY)
    has_error: bool | None = Field(description=_RULE_HAS_ERROR)
    conditions: RuleConditions | None = Field(description=_RULE_CONDITIONS)
    exceptions: RuleConditions | None = Field(description=_RULE_EXCEPTIONS)
    actions: RuleActions | None = Field(
        description=(
            "The actions that this rule takes on each matching message. Only the actions that the "
            + "rule sets appear. Null when Graph reports no action."
        )
    )

    @classmethod
    def from_rule(cls, rule: MessageRule) -> Self:
        assert rule.id is not None, "Graph returned a message rule with no id"
        return cls(
            uri=MailRuleHandle(rule.id).uri,
            display_name=rule.display_name,
            is_enabled=rule.is_enabled,
            sequence=rule.sequence,
            is_read_only=rule.is_read_only,
            has_error=rule.has_error,
            conditions=conditions_of(rule.conditions),
            exceptions=conditions_of(rule.exceptions),
            actions=actions_of(rule.actions),
        )


class RuleConditionsInput(BaseModel):
    body_contains: list[Annotated[str, Field(min_length=1)]] | None = Field(
        default=None,
        min_length=1,
        description=(
            "The strings that must appear in the body of an incoming message for the condition or "
            + "the exception to apply. Omit it when the body does not matter."
        ),
    )
    body_or_subject_contains: list[Annotated[str, Field(min_length=1)]] | None = Field(
        default=None,
        min_length=1,
        description=(
            "The strings that must appear in the body or in the subject of an incoming message "
            + "for the condition or the exception to apply. Omit it when neither matters."
        ),
    )
    categories: list[Annotated[str, Field(min_length=1)]] | None = Field(
        default=None,
        min_length=1,
        description=(
            "The names of the categories that an incoming message must have for the condition or "
            + "the exception to apply. outlook_list_categories lists the names."
        ),
    )
    from_addresses: list[str] | None = Field(
        default=None,
        min_length=1,
        description=(
            "The SMTP addresses of the senders for the condition or the exception, for example "
            + "`ada@example.com`. An incoming message must come from one of them. Omit it when "
            + "the sender does not matter."
        ),
    )
    has_attachments: Literal[True] | None = Field(
        default=None,
        description=(
            "Set true when an incoming message must have attachments for the condition or the "
            + "exception to apply. Omit it otherwise."
        ),
    )
    header_contains: list[Annotated[str, Field(min_length=1)]] | None = Field(
        default=None,
        min_length=1,
        description=(
            "The strings that must appear in the headers of an incoming message for the "
            + "condition or the exception to apply. Omit it when the headers do not matter."
        ),
    )
    importance: RuleImportance | None = Field(
        default=None,
        description=(
            "The importance that an incoming message must have for the condition or the "
            + "exception to apply. Omit it when the importance does not matter."
        ),
    )
    is_approval_request: Literal[True] | None = Field(
        default=None,
        description=(
            "Set true when an incoming message must be an approval request for the condition or "
            + "the exception to apply. Omit it otherwise."
        ),
    )
    is_automatic_forward: Literal[True] | None = Field(
        default=None,
        description=(
            "Set true when an incoming message must be an automatic forward for the condition or "
            + "the exception to apply. Omit it otherwise."
        ),
    )
    is_automatic_reply: Literal[True] | None = Field(
        default=None,
        description=(
            "Set true when an incoming message must be an automatic reply for the condition or "
            + "the exception to apply. Omit it otherwise."
        ),
    )
    is_encrypted: Literal[True] | None = Field(
        default=None,
        description=(
            "Set true when an incoming message must be encrypted for the condition or the "
            + "exception to apply. Omit it otherwise."
        ),
    )
    is_meeting_request: Literal[True] | None = Field(
        default=None,
        description=(
            "Set true when an incoming message must be a meeting request for the condition or the "
            + "exception to apply. Omit it otherwise."
        ),
    )
    is_meeting_response: Literal[True] | None = Field(
        default=None,
        description=(
            "Set true when an incoming message must be a meeting response for the condition or "
            + "the exception to apply. Omit it otherwise."
        ),
    )
    is_non_delivery_report: Literal[True] | None = Field(
        default=None,
        description=(
            "Set true when an incoming message must be a non-delivery report for the condition or "
            + "the exception to apply. Omit it otherwise."
        ),
    )
    is_permission_controlled: Literal[True] | None = Field(
        default=None,
        description=(
            "Set true when an incoming message must be permission controlled (RMS-protected) for "
            + "the condition or the exception to apply. Omit it otherwise."
        ),
    )
    is_read_receipt: Literal[True] | None = Field(
        default=None,
        description=(
            "Set true when an incoming message must be a read receipt for the condition or the "
            + "exception to apply. Omit it otherwise."
        ),
    )
    is_signed: Literal[True] | None = Field(
        default=None,
        description=(
            "Set true when an incoming message must be S/MIME-signed for the condition or the "
            + "exception to apply. Omit it otherwise."
        ),
    )
    is_voicemail: Literal[True] | None = Field(
        default=None,
        description=(
            "Set true when an incoming message must be a voice mail for the condition or the "
            + "exception to apply. Omit it otherwise."
        ),
    )
    message_action_flag: RuleActionFlag | None = Field(
        default=None,
        description=(
            "The flag-for-action value that an incoming message must have for the condition or "
            + "the exception to apply, for example `followUp`. Omit it when the flag does not "
            + "matter."
        ),
    )
    not_sent_to_me: Literal[True] | None = Field(
        default=None,
        description=(
            "Set true when the mailbox owner must not be a recipient of an incoming message for "
            + "the condition or the exception to apply. Omit it otherwise."
        ),
    )
    recipient_contains: list[Annotated[str, Field(min_length=1)]] | None = Field(
        default=None,
        min_length=1,
        description=(
            "The strings that must appear in the To or Cc recipients of an incoming message for "
            + "the condition or the exception to apply."
        ),
    )
    sender_contains: list[Annotated[str, Field(min_length=1)]] | None = Field(
        default=None,
        min_length=1,
        description=(
            "The strings that must appear in the sender (`from`) of an incoming message for the "
            + "condition or the exception to apply. Use it for a part of an address or a name."
        ),
    )
    sensitivity: RuleSensitivity | None = Field(
        default=None,
        description=(
            "The sensitivity that an incoming message must have for the condition or the "
            + "exception to apply. Omit it when the sensitivity does not matter."
        ),
    )
    sent_cc_me: Literal[True] | None = Field(
        default=None,
        description=(
            "Set true when the mailbox owner must be in the Cc recipients of an incoming message "
            + "for the condition or the exception to apply. Omit it otherwise."
        ),
    )
    sent_only_to_me: Literal[True] | None = Field(
        default=None,
        description=(
            "Set true when the mailbox owner must be the only recipient of an incoming message for "
            + "the condition or the exception to apply. Omit it otherwise."
        ),
    )
    sent_to_addresses: list[str] | None = Field(
        default=None,
        min_length=1,
        description=(
            "The SMTP addresses to which an incoming message must be sent for the condition or the "
            + "exception to apply, for example `team@example.com`. Omit it when the recipients do "
            + "not matter."
        ),
    )
    sent_to_me: Literal[True] | None = Field(
        default=None,
        description=(
            "Set true when the mailbox owner must be in the To recipients of an incoming message "
            + "for the condition or the exception to apply. Omit it otherwise."
        ),
    )
    sent_to_or_cc_me: Literal[True] | None = Field(
        default=None,
        description=(
            "Set true when the mailbox owner must be a To or Cc recipient of an incoming message "
            + "for the condition or the exception to apply."
        ),
    )
    subject_contains: list[Annotated[str, Field(min_length=1)]] | None = Field(
        default=None,
        min_length=1,
        description=(
            "The strings that must appear in the subject of an incoming message for the condition "
            + "or the exception to apply. Omit it when the subject does not matter."
        ),
    )
    within_size_range: SizeRangeKb | None = Field(
        default=None,
        description=(
            "The range of sizes, in kilobytes, that an incoming message must fall in for the "
            + "condition or the exception to apply. Omit it when the size does not matter."
        ),
    )


class RuleActionsInput(BaseModel):
    assign_categories: list[Annotated[str, Field(min_length=1)]] | None = Field(
        default=None,
        min_length=1,
        description=(
            "The names of the categories to put on each matching message. "
            + "outlook_list_categories lists the names that the mailbox has. Omit it to put no "
            + "category on the messages."
        ),
    )
    copy_to_folder: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "The folder in which the rule puts a copy of each matching message. It takes the same "
            + "values as `move_to_folder`: a folder handle, or a well-known folder name."
        ),
    )
    delete: Literal[True] | None = Field(
        default=None,
        description=(
            "Set true to move each matching message to Deleted Items. The user can move a message "
            + "back from there. No action of this tool erases a message permanently."
        ),
    )
    forward_as_attachment_to: list[str] | None = Field(
        default=None,
        min_length=1,
        description=(
            "The SMTP addresses to which the rule forwards each matching message as an "
            + "attachment, for example `dana@example.com`. Give one address in each entry."
        ),
    )
    forward_to: list[str] | None = Field(
        default=None,
        min_length=1,
        description=(
            "The SMTP addresses to which the rule forwards a copy of each matching message, for "
            + "example `dana@example.com`. Give one address in each entry."
        ),
    )
    mark_as_read: Literal[True] | None = Field(
        default=None,
        description=(
            "Set true to mark each matching message as read when it arrives. Omit it to keep the "
            + "read status of each message as it is."
        ),
    )
    mark_importance: RuleImportance | None = Field(
        default=None,
        description=(
            "The importance that the rule sets on each matching message. Omit it to keep the "
            + "importance of each message as it is."
        ),
    )
    move_to_folder: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "The folder to which the rule moves each matching message. Give the `uri` of an "
            + "outlook_browse_folders row, or a well-known folder name: `inbox`, `sentitems`, "
            + "`drafts`, `archive`, `deleteditems`, `junkemail`, or `clutter`."
        ),
    )
    redirect_to: list[str] | None = Field(
        default=None,
        min_length=1,
        description=(
            "The SMTP addresses to which the rule redirects each matching message, with the "
            + "original sender kept, for example `dana@example.com`. Give one address in each "
            + "entry."
        ),
    )
    stop_processing_rules: Literal[True] | None = Field(
        default=None,
        description=(
            "Set true to stop Outlook from running the rules that come after this rule in "
            + "`sequence`. Omit it to let the later rules run."
        ),
    )

    @property
    def sets_nothing(self) -> bool:
        return not self.model_dump(exclude_none=True)


def predicates_for(conditions: RuleConditionsInput | None) -> MessageRulePredicates | None:
    if conditions is None:
        return None
    predicates = MessageRulePredicates(
        body_contains=conditions.body_contains,
        body_or_subject_contains=conditions.body_or_subject_contains,
        categories=conditions.categories,
        from_addresses=_recipients(conditions.from_addresses),
        has_attachments=conditions.has_attachments,
        header_contains=conditions.header_contains,
        importance=None if conditions.importance is None else Importance(conditions.importance),
        is_approval_request=conditions.is_approval_request,
        is_automatic_forward=conditions.is_automatic_forward,
        is_automatic_reply=conditions.is_automatic_reply,
        is_encrypted=conditions.is_encrypted,
        is_meeting_request=conditions.is_meeting_request,
        is_meeting_response=conditions.is_meeting_response,
        is_non_delivery_report=conditions.is_non_delivery_report,
        is_permission_controlled=conditions.is_permission_controlled,
        is_read_receipt=conditions.is_read_receipt,
        is_signed=conditions.is_signed,
        is_voicemail=conditions.is_voicemail,
        message_action_flag=(
            None
            if conditions.message_action_flag is None
            else MessageActionFlag(conditions.message_action_flag)
        ),
        not_sent_to_me=conditions.not_sent_to_me,
        recipient_contains=conditions.recipient_contains,
        sender_contains=conditions.sender_contains,
        sensitivity=(
            None if conditions.sensitivity is None else Sensitivity(conditions.sensitivity)
        ),
        sent_cc_me=conditions.sent_cc_me,
        sent_only_to_me=conditions.sent_only_to_me,
        sent_to_addresses=_recipients(conditions.sent_to_addresses),
        sent_to_me=conditions.sent_to_me,
        sent_to_or_cc_me=conditions.sent_to_or_cc_me,
        subject_contains=conditions.subject_contains,
        within_size_range=_size_range(conditions.within_size_range),
    )
    return None if conditions_of(predicates) is None else predicates


@dataclass(frozen=True, slots=True)
class RuleFolders:
    move_to_folder: str | None
    copy_to_folder: str | None
    hidden: bool


def actions_for(actions: RuleActionsInput, folders: RuleFolders) -> MessageRuleActions:
    return MessageRuleActions(
        assign_categories=actions.assign_categories,
        copy_to_folder=folders.copy_to_folder,
        delete=actions.delete,
        forward_as_attachment_to=_recipients(actions.forward_as_attachment_to),
        forward_to=_recipients(actions.forward_to),
        mark_as_read=actions.mark_as_read,
        mark_importance=(
            None if actions.mark_importance is None else Importance(actions.mark_importance)
        ),
        move_to_folder=folders.move_to_folder,
        redirect_to=_recipients(actions.redirect_to),
        stop_processing_rules=actions.stop_processing_rules,
    )


def unusable_addresses(
    *parts: RuleConditionsInput | RuleActionsInput | None,
) -> list[str]:
    entries = [entry for part in parts for entry in _entered_addresses(part)]
    return [entry for entry in entries if ONE_ADDRESS.match(entry.strip()) is None]


def unusable_folders(actions: RuleActionsInput | None) -> list[str]:
    if actions is None:
        return []
    asked = (actions.move_to_folder, actions.copy_to_folder)
    return [ref for ref in asked if ref is not None and _folder_segment(ref) is None]


async def rule_folders(client: GraphServiceClient, actions: RuleActionsInput) -> RuleFolders:
    moved_into = await _rule_folder(client, actions.move_to_folder)
    copied_into = await _rule_folder(client, actions.copy_to_folder)
    found = [folder for folder in (moved_into, copied_into) if folder is not None]
    return RuleFolders(
        move_to_folder=None if moved_into is None else moved_into.id,
        copy_to_folder=None if copied_into is None else copied_into.id,
        hidden=any(folder.is_hidden is True for folder in found),
    )


def forwarding_question(
    verb: str,
    name: str,
    actions: MessageRuleActions | None,
    conditions: MessageRulePredicates | None,
) -> str | None:
    reach = _reach(actions)
    if not reach:
        return None
    scope = (
        "The rule has no condition, so it acts on every incoming message."
        if conditions_of(conditions) is None
        else "The rule acts only on the incoming messages that match its conditions."
    )
    return (
        f"{verb} the inbox rule {cut_for_a_question(name)!r}? {' '.join(reach)} {scope} This "
        + "connector cannot recall a message that the rule sends."
    )


def rule_confirmation_id(*parts: BaseModel | str | int | bool | None) -> str:
    canonical = [
        part.model_dump(mode="json", exclude_none=True) if isinstance(part, BaseModel) else part
        for part in parts
    ]
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()


def inbox_rules(client: GraphServiceClient) -> MessageRulesRequestBuilder:
    return client.me.mail_folders.by_mail_folder_id(_INBOX).message_rules


def rule_of(client: GraphServiceClient, handle: MailRuleHandle) -> MessageRuleItemRequestBuilder:
    return inbox_rules(client).by_message_rule_id(handle.rule_id)


async def read_rule(client: GraphServiceClient, handle: MailRuleHandle) -> MessageRule:
    with graph_step(STEP_READ_RULE):
        rule = await rule_of(client, handle).get(
            request_configuration=RequestConfiguration[_RuleQuery](
                query_parameters=_RuleQuery(select=list(RULE_FIELDS))
            )
        )
    assert rule is not None, "Graph answered a rule read with no rule and no error"
    return rule


async def _rule_folder(client: GraphServiceClient, ref: str | None) -> MailFolder | None:
    if ref is None:
        return None
    segment = _folder_segment(ref)
    assert segment is not None, "the folder references were parsed before any Graph call"
    with graph_step(STEP_RULE_FOLDER):
        folder = await client.me.mail_folders.by_mail_folder_id(segment).get(
            request_configuration=RequestConfiguration[_FolderQuery](
                query_parameters=_FolderQuery(select=list(_FOLDER_FIELDS))
            )
        )
    assert folder is not None and folder.id is not None, (
        "Graph answered a mail folder read with no folder id"
    )
    return folder


def _folder_segment(ref: str) -> str | None:
    if ref in _WELL_KNOWN_FOLDERS:
        return ref
    handle = mail_folder_handle(ref)
    return None if handle is None else handle.folder_id


def _entered_addresses(part: RuleConditionsInput | RuleActionsInput | None) -> list[str]:
    match part:
        case None:
            lists: tuple[list[str] | None, ...] = ()
        case RuleConditionsInput():
            lists = (part.from_addresses, part.sent_to_addresses)
        case RuleActionsInput():
            lists = (part.forward_to, part.forward_as_attachment_to, part.redirect_to)
    return [entry for entries in lists for entry in entries or []]


def _recipients(addresses: list[str] | None) -> list[Recipient] | None:
    if addresses is None:
        return None
    return [Recipient(email_address=EmailAddress(address=address.strip())) for address in addresses]


def _size_range(size: SizeRangeKb | None) -> SizeRange | None:
    if size is None or (size.minimum_kb is None and size.maximum_kb is None):
        return None
    return SizeRange(minimum_size=size.minimum_kb, maximum_size=size.maximum_kb)


def _reach(actions: MessageRuleActions | None) -> list[str]:
    if actions is None:
        return []
    sent = (
        ("Outlook forwards a copy of each matching message to", actions.forward_to),
        (
            "Outlook forwards each matching message as an attachment to",
            actions.forward_as_attachment_to,
        ),
        ("Outlook redirects each matching message to", actions.redirect_to),
    )
    return [
        f"{how} {_listed(addresses)}."
        for how, recipients in sent
        if (addresses := _addresses(recipients))
    ]


def _listed(parts: Sequence[str]) -> str:
    if len(parts) <= 2:
        return " and ".join(parts)
    return f"{', '.join(parts[:-1])}, and {parts[-1]}"


def _addresses(recipients: list[Recipient] | None) -> list[str]:
    named: list[str] = []
    for recipient in recipients or []:
        email = recipient.email_address
        if email is None:
            continue
        address = email.address if email.address else email.name
        if address is not None:
            named.append(address)
    return named


def _deletes(actions: MessageRuleActions | None) -> bool | None:
    if actions is None:
        return None
    said = [flag for flag in (actions.delete, actions.permanent_delete) if flag is not None]
    return any(said) if said else None
