from typing import Self

from msgraph.generated.models.importance import Importance
from msgraph.generated.models.message_action_flag import MessageActionFlag
from msgraph.generated.models.message_rule import MessageRule
from msgraph.generated.models.message_rule_actions import MessageRuleActions
from msgraph.generated.models.message_rule_predicates import MessageRulePredicates
from msgraph.generated.models.recipient import Recipient
from msgraph.generated.models.sensitivity import Sensitivity
from msgraph.generated.models.size_range import SizeRange
from pydantic import BaseModel, Field

from office_365_mcp.shared.handles import MailRuleHandle


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
            "True when the mailbox owner must be in the To recipients or in the Cc recipients of "
            + "an incoming message for the condition or the exception to apply."
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
        importance=_spelled(predicates.importance),
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
        message_action_flag=_spelled(predicates.message_action_flag),
        not_sent_to_me=predicates.not_sent_to_me,
        recipient_contains=predicates.recipient_contains or None,
        sender_contains=predicates.sender_contains or None,
        sensitivity=_spelled(predicates.sensitivity),
        sent_cc_me=predicates.sent_cc_me,
        sent_only_to_me=predicates.sent_only_to_me,
        sent_to_addresses=_addresses(predicates.sent_to_addresses) or None,
        sent_to_me=predicates.sent_to_me,
        sent_to_or_cc_me=predicates.sent_to_or_cc_me,
        subject_contains=predicates.subject_contains or None,
        within_size_range=SizeRangeKb.from_size_range(predicates.within_size_range),
    )
    return conditions if conditions.model_dump() else None


class InboxRule(BaseModel):
    uri: str = Field(
        description=(
            "This is the handle of the rule, `outlook:///rules/{id}`. If this deployment exposes "
            + "outlook_disable_mail_rule, pass this handle to that tool to disable the rule. No "
            + "tool here can delete a rule."
        )
    )
    display_name: str | None = Field(
        description=(
            "The name of the rule. It is a label, and not a description of what the rule does. "
            + "Null if Graph recorded none."
        )
    )
    is_enabled: bool | None = Field(
        description=(
            "True when the rule runs. False when the rule exists but does nothing now. Null if "
            + "Graph does not say."
        )
    )
    sequence: int | None = Field(
        description=(
            "The position of the rule in the order in which Outlook runs the rules, lowest "
            + "first. Null if Graph does not say."
        )
    )
    is_read_only: bool | None = Field(
        description=(
            "True for a rule that the rules API cannot change or delete. A read-only rule still "
            + "runs. Null if Graph does not say."
        )
    )
    has_error: bool | None = Field(
        description=(
            "True when Microsoft 365 reports that the rule is in an error condition. Null if "
            + "Graph does not say."
        )
    )
    conditions: RuleConditions | None = Field(
        description=(
            "The conditions that trigger the actions of this rule. Only the predicates that the "
            + "rule sets appear. Null when Graph reports no condition."
        )
    )
    exceptions: RuleConditions | None = Field(
        description=(
            "The exception conditions of this rule, in the same shape as `conditions`. Only the "
            + "predicates that the rule sets appear. Null when Graph reports no exception."
        )
    )
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


def _spelled(value: Importance | MessageActionFlag | Sensitivity | None) -> str | None:
    return None if value is None else str.__str__(value)
