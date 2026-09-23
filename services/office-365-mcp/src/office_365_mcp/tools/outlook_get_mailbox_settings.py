"""`outlook_get_mailbox_settings` — what is quietly acting on this mailbox, and what cannot be seen.

**This is a safety tool before it is a management tool, and its answer has a hole in it that must
travel with the answer.** Exchange mailbox-level forwarding — `Set-Mailbox -ForwardingSmtpAddress`,
and the Forwarding box in the Exchange admin center — is not an inbox rule. It is also not a
mailbox setting Microsoft Graph publishes. `mailboxSettings` carries exactly `archiveFolder`,
`automaticRepliesSetting`, `dateFormat`, `delegateMeetingMessageDeliveryOptions`, `language`,
`timeFormat`, `timeZone`, `userPurpose` and `workingHours`
(https://learn.microsoft.com/en-us/graph/api/resources/mailboxsettings). No `forwardingSmtpAddress`
is among them, and no other endpoint this connector can call carries one either. So "no forwarding
rule found" is NOT "your mail is not being forwarded", and `covers_mailbox_level_forwarding` is a
constant `false` on every response that says so in as many words. A confident wrong answer here
tells a user their mail is private, while a copy of it leaves the tenant. That is the worst
failure this tool can produce.

**Every action is a named field, never a nested blob.** Graph reports what a rule does inside
`actions`. A model handed that object must infer "this forwards my mail out of the organization"
from a list of recipients. It must know which key to look under. The rule that forwards mail is
the whole reason this tool exists. So this tool reads `forwards_to`, `redirects_to` and
`forward_as_attachment_to` off it, and answers them as plain address lists.

**This tool does not read a rule's conditions.** This answers what a rule *does*, not which mail
it does it to. So a forwarding rule here can forward everything, or one sender's mail. Outlook is
the place to see which. Reporting a truncated reading of `conditions` and `exceptions` looks like
an answer to a question this tool did not ask. The same goes for the actions that only sort mail.
This tool does not report `copyToFolder`, `markImportance` or `assignCategories`.

**`include` exists so one question costs one request.** The three collections are three separate
Graph calls under one permission. So a caller who wants the automatic reply does not need a rules
listing and a categories listing just to find out. Anything `include` did not ask for comes back
null rather than empty: an empty list reads as "there are none", which is a different claim
entirely.

**The rules are the Inbox folder's rules.** Graph hangs `messageRules` off `mailFolder`, but
documents the collection as "the rules that apply to the user's Inbox folder"
(https://learn.microsoft.com/en-us/graph/api/mailfolder-list-messagerules), so the well-known name
`inbox` is the address rather than a folder handle a caller passes in.

**This tool takes no `mailbox` argument.** Microsoft publishes no `.Shared` variant of
`MailboxSettings.Read` — the permissions reference lists only `MailboxSettings.Read` and
`MailboxSettings.ReadWrite`, delegated, with no `.Shared` sibling
(https://learn.microsoft.com/en-us/graph/permissions-reference) — and this connector holds only
delegated permissions, never application ones. Multiple independent reports of
`GET /users/{id}/mailboxSettings` and `GET /users/{id}/mailFolders/inbox/messageRules` under a
delegated `MailboxSettings.Read` token confirm the practical consequence: Graph answers 403 for
any `{id}` but the caller's own, Full Access mailbox permission notwithstanding
(https://github.com/microsoftgraph/msgraph-sdk-powershell/issues/2966). Application permissions
are the only documented route to another mailbox's settings or rules, and this connector's
On-Behalf-Of design never holds one. A `mailbox` argument here would be silently unreachable.
"""

from collections.abc import Mapping
from typing import Annotated, Literal, Self

import httpx
from fastmcp import FastMCP
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.automatic_replies_setting import AutomaticRepliesSetting
from msgraph.generated.models.automatic_replies_status import AutomaticRepliesStatus
from msgraph.generated.models.date_time_time_zone import DateTimeTimeZone
from msgraph.generated.models.external_audience_scope import ExternalAudienceScope
from msgraph.generated.models.message_rule import MessageRule
from msgraph.generated.models.message_rule_actions import MessageRuleActions
from msgraph.generated.models.outlook_category import OutlookCategory
from msgraph.generated.models.recipient import Recipient
from msgraph.generated.users.item.mail_folders.item.message_rules.message_rules_request_builder import (  # noqa: E501
    MessageRulesRequestBuilder,
)
from msgraph.generated.users.item.mailbox_settings.mailbox_settings_request_builder import (
    MailboxSettingsRequestBuilder,
)
from msgraph.generated.users.item.outlook.master_categories.master_categories_request_builder import (  # noqa: E501
    MasterCategoriesRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import CollectedItems, collect_pages, graph_errors, graph_step
from office_365_mcp.shared.handles import MailRuleHandle
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "outlook_get_mailbox_settings"

STEP_SETTINGS = "mailbox_settings"
STEP_RULES = "mail_rules"
STEP_CATEGORIES = "mail_categories"

# One permission covers all three collections: Microsoft documents `MailboxSettings.Read` as the
# delegated permission for the rule listing, for `mailboxSettings` and for the master categories.
GRAPH_PERMISSIONS: tuple[str, ...] = ("MailboxSettings.Read",)

# `rules` rather than the default, so the example is exactly one Graph call. The refusal it
# produces is the rules listing's, rather than whichever of the three ran first.
GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"include": "rules"}

# The default 404 advice says to check that the id came from a tool response, verbatim. That
# advice cannot apply here: this tool takes no id at all.
GRAPH_NOT_FOUND = (
    "Microsoft 365 has nothing to answer this with. outlook_get_mailbox_settings takes no id — it "
    + "reads the signed-in user's own mailbox — so nothing about the arguments caused this. Most "
    + "likely this account has no Exchange Online mailbox, which is what an unlicensed or "
    + "on-premises account looks like from here. Retrying will fail identically, and no other "
    + "`include` will succeed either."
)

# Bounds on the two collections, far above what Exchange holds in practice. A size quota well
# under this caps a mailbox's rules, and categories are a hand-made list.
MAX_RULES = 200
MAX_CATEGORIES = 500

# Graph's locale-independent well-known name for the Inbox, which reaches it in a mailbox of any
# language. The rules collection exists on this one folder.
_INBOX_FOLDER = "inbox"

# Every property the answer reads. `conditions` and `exceptions` are deliberately absent — see the
# module docstring.
_RULE_FIELDS: tuple[str, ...] = (
    "id",
    "displayName",
    "isEnabled",
    "sequence",
    "isReadOnly",
    "hasError",
    "actions",
)

# The one property of the nine that this tool is about. Microsoft documents that `mailboxSettings`
# requires `$select` to retrieve it. Asking for the rest returns a working-hours block nothing
# here reports.
_SETTINGS_FIELDS: tuple[str, ...] = ("automaticRepliesSetting",)

_CATEGORY_FIELDS: tuple[str, ...] = ("displayName",)

# Bound rather than aliased with `type`. These names serve as the query parameters' constructor,
# and also as `RequestConfiguration`'s argument. A `TypeAliasType` is not callable.
_RulesQuery = MessageRulesRequestBuilder.MessageRulesRequestBuilderGetQueryParameters
_SettingsQuery = MailboxSettingsRequestBuilder.MailboxSettingsRequestBuilderGetQueryParameters
_CategoriesQuery = MasterCategoriesRequestBuilder.MasterCategoriesRequestBuilderGetQueryParameters

type Include = Literal["all", "rules", "replies", "categories"]

# Microsoft's own spellings, so a value here matches the documentation and the admin center rather
# than a vocabulary invented in this file.
type AutoReplyStatus = Literal["disabled", "alwaysEnabled", "scheduled"]
type ExternalAudience = Literal["none", "contactsOnly", "all"]

_DESCRIPTION = """\
Shows what quietly acts on the signed-in user's mailbox — the inbox rules, the automatic reply, \
and the categories — for "is something forwarding my mail?", "am I still out of office?", and \
"which rules move my mail".

Notes:
- Cannot see Exchange mailbox-level forwarding, which Microsoft Graph does not publish \
anywhere. An empty rule list, or rules that forward nothing, does not prove that nobody \
forwards this mailbox's mail.
- Reports what each rule does, never which mail it targets — a forwarding rule can act on \
everything or on one sender's mail. Outlook shows which.
- Each rule reports what it does as named fields — `forwards_to`, `redirects_to`, \
`moves_to_folder`, and the rest — never as a nested action object.
"""


class InboxRule(BaseModel):
    """One inbox rule, read as what it does to mail rather than as Graph's `actions` object.

    This tool does not report the conditions that trigger it, so a rule here can act on every
    message or on one sender's. Outlook is where that is visible.
    """

    uri: str = Field(
        description=(
            "This rule's handle, `outlook:///rules/{id}`, names this exact rule for a later "
            + "answer. No tool here can change or delete a rule. Do that in Outlook or the "
            + "Exchange admin center."
        )
    )
    display_name: str | None = Field(
        description=(
            "The rule's name, chosen by whoever created it — a label, not a description. A "
            + "rule called `Newsletters` can still forward mail out of the organization. Null "
            + "when Graph recorded none."
        )
    )
    is_enabled: bool | None = Field(
        description=(
            "Whether the rule runs. False means it exists but currently does nothing. It is "
            + "not gone, because re-enabling it takes one click. So report a disabled "
            + "forwarding rule too. Null when Graph did not say."
        )
    )
    sequence: int | None = Field(
        description=(
            "The order Outlook evaluates rules in, lowest first. Null when Graph did not say."
        )
    )
    is_read_only: bool | None = Field(
        description=(
            "True for a rule the rules API cannot modify, usually one written by another client "
            + "or an administrator. It still runs. Null when Graph did not say."
        )
    )
    has_error: bool | None = Field(
        description=(
            "True when Microsoft 365 marked the rule broken, commonly because it names a folder "
            + "or an address that no longer exists. A rule in error can do only part of what "
            + "its actions describe. Null when Graph did not say."
        )
    )
    forwards_to: list[str] = Field(
        description=(
            "Addresses this rule forwards a copy of the message to — the field this tool exists "
            + "for. An address outside the user's own domain means copies of their mail leave "
            + "the organization automatically. Each entry is the SMTP address Graph recorded, or "
            + "the display name when it recorded none. Empty means this rule forwards nothing. "
            + "It says nothing about other rules, or about mailbox-level forwarding, which this "
            + "tool cannot see at all."
        )
    )
    redirects_to: list[str] = Field(
        description=(
            "Addresses this rule redirects the message to. A redirect preserves the original "
            + "sender, so a reply goes back to them rather than to this user. This is harder to "
            + "notice than a forward, but it is not less serious. Read it the same way as "
            + "`forwards_to`."
        )
    )
    forward_as_attachment_to: list[str] = Field(
        description=(
            "Addresses this rule forwards the message to as an attachment, headers included. "
            + "Read it the same way as `forwards_to`."
        )
    )
    moves_to_folder: str | None = Field(
        description=(
            "The Graph id of the folder this rule moves the message to. Null when the rule "
            + "moves nothing. It is opaque on its own. outlook_browse_folders reports id and "
            + "name together. Browse there to identify it. A rule that files mail out of the "
            + "Inbox is why a message can look like it never arrived."
        )
    )
    deletes: bool | None = Field(
        description=(
            "True when the rule deletes the message. It can move the message to Deleted Items, "
            + "where the user can still find it. Or it can delete the message permanently, "
            + "where nobody can find it again. This field does not distinguish the two. Null "
            + "when Graph reported neither."
        )
    )
    marks_as_read: bool | None = Field(
        description=(
            "True when the rule marks the message read on arrival, which is how mail can arrive "
            + "already read and unnoticed. Null when Graph did not say."
        )
    )
    stops_processing_more_rules: bool | None = Field(
        description=(
            "True when Outlook never evaluates a rule with a higher `sequence` for a message "
            + "this one matched. So a rule further down the list can look active, yet never run "
            + "for mail this one already handled. Null when Graph did not say."
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


class ScheduledMoment(BaseModel):
    """One end of an automatic reply's schedule, as the date and the zone Graph reports it in."""

    date_time: str | None = Field(
        description=(
            "The moment, in Graph's combined `{date}T{time}` spelling with no offset. Read it "
            + "together with `time_zone`. Null when Graph recorded none."
        )
    )
    time_zone: str | None = Field(
        description=(
            "The zone `date_time` is expressed in, usually `UTC`. Never assume it. A schedule "
            + "read in the wrong zone reports an expired auto-reply as still live."
        )
    )

    @classmethod
    def from_moment(cls, moment: DateTimeTimeZone | None) -> Self | None:
        if moment is None:
            return None
        return cls(date_time=moment.date_time, time_zone=moment.time_zone)


class AutomaticReply(BaseModel):
    """The automatic reply, which answers every future sender until it is switched off."""

    status: AutoReplyStatus | None = Field(
        description=(
            "`disabled` — sends nothing. `alwaysEnabled` — answers every incoming message with "
            + "no end date. `scheduled` — answers only between `scheduled_start` and "
            + "`scheduled_end`. Null when Graph reported none. Anything but `disabled` means the "
            + "reply text below reaches people right now."
        )
    )
    external_audience: ExternalAudience | None = Field(
        description=(
            "Who outside this organization receives `external_reply_message`. `none` for "
            + "nobody (colleagues only), `contactsOnly` for senders in the user's contacts, "
            + "`all` for every outside sender including strangers and spam. Null when Graph did "
            + "not say."
        )
    )
    scheduled_start: ScheduledMoment | None = Field(
        description=(
            "When a `scheduled` reply starts. It is meaningless unless `status` is `scheduled`. "
            + "A past date on a `disabled` reply is leftover, not evidence."
        )
    )
    scheduled_end: ScheduledMoment | None = Field(
        description=(
            "When a `scheduled` reply stops, on the same terms as `scheduled_start`. An "
            + "`alwaysEnabled` reply has no end, whatever this says."
        )
    )
    internal_reply_message: str | None = Field(
        description=(
            "The reply sent to senders inside this organization, as Graph stored it — usually "
            + "HTML rather than plain text. Null when none is set."
        )
    )
    external_reply_message: str | None = Field(
        description=(
            "The reply sent to senders outside this organization, subject to "
            + "`external_audience`. Read it for what it gives away. Examples are dates away, a "
            + "deputy's address, or a phone number. This matters beyond whether a reply is on. "
            + "Null when none is set."
        )
    )

    @classmethod
    def from_setting(cls, setting: AutomaticRepliesSetting | None) -> Self:
        """Always a reply object once replies were asked for. A mailbox Graph reported no setting
        for answers every field null, which is "Microsoft said nothing" and not "there is none"."""
        if setting is None:
            return cls(
                status=None,
                external_audience=None,
                scheduled_start=None,
                scheduled_end=None,
                internal_reply_message=None,
                external_reply_message=None,
            )
        return cls(
            status=_reply_status(setting.status),
            external_audience=_external_audience(setting.external_audience),
            scheduled_start=ScheduledMoment.from_moment(setting.scheduled_start_date_time),
            scheduled_end=ScheduledMoment.from_moment(setting.scheduled_end_date_time),
            internal_reply_message=setting.internal_reply_message,
            external_reply_message=setting.external_reply_message,
        )


class MailboxSettingsReport(BaseModel):
    """What acts on this mailbox, and — as a field rather than a caveat — what is not visible
    from here at all."""

    covers_mailbox_level_forwarding: Literal[False] = Field(
        default=False,
        description=(
            "This is always false. Exchange mailbox-level forwarding — set with "
            + "`Set-Mailbox -ForwardingSmtpAddress` or the Forwarding box in the Exchange admin "
            + "center — is invisible to every endpoint this connector can call. "
            + "`mailboxSettings` has no forwarding property. So an empty `rules` list, or rules "
            + "that forward nothing, does not prove that nobody forwards this mailbox's mail. "
            + "Say that to the user. Do not reassure them. To rule it out, use the Exchange "
            + "admin center or `Get-Mailbox | Select ForwardingSmtpAddress, ForwardingAddress`."
        ),
    )
    rules: list[InboxRule] | None = Field(
        description=(
            "The Inbox rules, in the order Graph returned them. Read `sequence` for the order "
            + "they run in. Null when `include` did not ask for them. Empty means no inbox "
            + "rules exist. Before you treat an empty list as nothing that touches this mail, "
            + "see `covers_mailbox_level_forwarding` too."
        )
    )
    rules_capped: bool | None = Field(
        description=(
            f"True when more than {MAX_RULES} rules were on offer and the listing stopped, so "
            + "`rules` is missing some. This is practically always false, since Exchange caps a "
            + "mailbox's rules well below that. Null when `include` did not ask for rules."
        )
    )
    automatic_reply: AutomaticReply | None = Field(
        description=(
            "The automatic reply, present whenever `include` asked for it — including for a "
            + "mailbox Graph reported no setting for, whose fields are then all null. Null only "
            + "means `include` did not ask for it."
        )
    )
    categories: list[str] | None = Field(
        description=(
            "The display names of the categories this mailbox can tag mail with — free strings "
            + "with no fixed vocabulary. So a category named `Confidential` or `Done` means "
            + "whatever its owner meant by it. Null when `include` did not ask for them. Empty "
            + "means the mailbox has none."
        )
    )
    categories_capped: bool | None = Field(
        description=(
            f"True when more than {MAX_CATEGORIES} categories were on offer and the listing "
            + "stopped, so `categories` is missing some. Null when `include` did not ask for "
            + "them."
        )
    )


async def get_mailbox_settings(
    client: GraphServiceClient, *, include: Include = "all"
) -> MailboxSettingsReport:
    wants_rules = include in ("all", "rules")
    wants_replies = include in ("all", "replies")
    wants_categories = include in ("all", "categories")

    with graph_errors(TOOL_NAME):
        rules = await _inbox_rules(client) if wants_rules else None
        setting = await _automatic_reply(client) if wants_replies else None
        categories = await _categories(client) if wants_categories else None

    return MailboxSettingsReport(
        rules=None if rules is None else [InboxRule.from_rule(rule) for rule in rules.items],
        rules_capped=None if rules is None else rules.capped,
        # Built from `wants_replies` and not from `setting`, which is None for a mailbox Graph
        # reported no automatic reply for. That is not the same answer as "never asked".
        automatic_reply=AutomaticReply.from_setting(setting) if wants_replies else None,
        categories=(
            None
            if categories is None
            else [_category_name(category) for category in categories.items]
        ),
        categories_capped=None if categories is None else categories.capped,
    )


async def _inbox_rules(client: GraphServiceClient) -> CollectedItems[MessageRule]:
    with graph_step(STEP_RULES):
        first_page = await client.me.mail_folders.by_mail_folder_id(
            _INBOX_FOLDER
        ).message_rules.get(
            request_configuration=RequestConfiguration[_RulesQuery](
                query_parameters=_RulesQuery(select=list(_RULE_FIELDS), top=MAX_RULES)
            )
        )
        assert first_page is not None, "Graph answered a rule listing with no collection"
        return await collect_pages(first_page, client, limit=MAX_RULES)


async def _automatic_reply(client: GraphServiceClient) -> AutomaticRepliesSetting | None:
    with graph_step(STEP_SETTINGS):
        settings = await client.me.mailbox_settings.get(
            request_configuration=RequestConfiguration[_SettingsQuery](
                query_parameters=_SettingsQuery(select=list(_SETTINGS_FIELDS))
            )
        )
    return None if settings is None else settings.automatic_replies_setting


async def _categories(client: GraphServiceClient) -> CollectedItems[OutlookCategory]:
    with graph_step(STEP_CATEGORIES):
        first_page = await client.me.outlook.master_categories.get(
            request_configuration=RequestConfiguration[_CategoriesQuery](
                query_parameters=_CategoriesQuery(select=list(_CATEGORY_FIELDS), top=MAX_CATEGORIES)
            )
        )
        assert first_page is not None, "Graph answered a category listing with no collection"
        return await collect_pages(first_page, client, limit=MAX_CATEGORIES)


def _category_name(category: OutlookCategory) -> str:
    assert category.display_name is not None, "Graph returned a category with no display name"
    return category.display_name


def _addresses(recipients: list[Recipient] | None) -> list[str]:
    """Where a rule sends mail, one entry per recipient.

    The display name stands in when Graph recorded no address, rather than dropping the
    recipient. A destination this tool leaves out is a destination the user does not know about.
    """
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
    """Whether the rule destroys the message, by either of Graph's two spellings.

    This function folds them together, because both answer "does this rule delete my mail" with
    yes. A field that reports only `delete` answers a rule that permanently deletes with silence.
    """
    if actions is None:
        return None
    said = [flag for flag in (actions.delete, actions.permanent_delete) if flag is not None]
    return any(said) if said else None


def _reply_status(status: AutomaticRepliesStatus | None) -> AutoReplyStatus | None:
    match status:
        case None:
            return None
        case AutomaticRepliesStatus.Disabled:
            return "disabled"
        case AutomaticRepliesStatus.AlwaysEnabled:
            return "alwaysEnabled"
        case AutomaticRepliesStatus.Scheduled:
            return "scheduled"


def _external_audience(audience: ExternalAudienceScope | None) -> ExternalAudience | None:
    match audience:
        case None:
            return None
        case ExternalAudienceScope.None_:
            return "none"
        case ExternalAudienceScope.ContactsOnly:
            return "contactsOnly"
        case ExternalAudienceScope.All:
            return "all"


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Get Mailbox Settings",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def outlook_get_mailbox_settings(
        include: Annotated[
            Include,
            Field(
                description=(
                    "Which of the three to read, one Graph call each. `all` reads every one. "
                    + '`rules` reads only the inbox rules — the answer to "is something '
                    + 'forwarding my mail". `replies` reads only the automatic reply. '
                    + "`categories` reads only the category names. Whatever the caller does not "
                    + "ask for comes back null, never empty."
                )
            ),
        ] = "all",
        client: GraphServiceClient = graph,
    ) -> MailboxSettingsReport:
        return await get_mailbox_settings(client, include=include)
