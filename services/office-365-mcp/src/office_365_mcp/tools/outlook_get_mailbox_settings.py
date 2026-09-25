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

GRAPH_PERMISSIONS: tuple[str, ...] = ("MailboxSettings.Read",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"include": "rules"}

GRAPH_NOT_FOUND = (
    "Microsoft 365 has nothing to answer this with. outlook_get_mailbox_settings takes no id — it "
    + "reads the signed-in user's own mailbox — so nothing about the arguments caused this. Most "
    + "likely this account has no Exchange Online mailbox, which is what an unlicensed or "
    + "on-premises account looks like from here. Retrying will fail identically, and no other "
    + "`include` will succeed either."
)

MAX_RULES = 200
MAX_CATEGORIES = 500

_INBOX_FOLDER = "inbox"

_RULE_FIELDS: tuple[str, ...] = (
    "id",
    "displayName",
    "isEnabled",
    "sequence",
    "isReadOnly",
    "hasError",
    "actions",
)

_SETTINGS_FIELDS: tuple[str, ...] = ("automaticRepliesSetting",)

_CATEGORY_FIELDS: tuple[str, ...] = ("displayName",)

_RulesQuery = MessageRulesRequestBuilder.MessageRulesRequestBuilderGetQueryParameters
_SettingsQuery = MailboxSettingsRequestBuilder.MailboxSettingsRequestBuilderGetQueryParameters
_CategoriesQuery = MasterCategoriesRequestBuilder.MasterCategoriesRequestBuilderGetQueryParameters

type Include = Literal["all", "rules", "replies", "categories"]

type AutoReplyStatus = Literal["disabled", "alwaysEnabled", "scheduled"]
type ExternalAudience = Literal["none", "contactsOnly", "all"]

_DESCRIPTION = (
    "Shows what quietly acts on the mailbox — inbox rules, automatic replies, and categories — "
    "though it cannot see Exchange mailbox-level forwarding, so this does not prove that nobody "
    "forwards this mailbox's mail."
)


class InboxRule(BaseModel):
    uri: str = Field(
        description=(
            "This rule's handle, `outlook:///rules/{id}`; no tool here can change or delete a "
            + "rule."
        )
    )
    display_name: str | None = Field(
        description="The rule's name; a label, not a description. Null if Graph recorded none."
    )
    is_enabled: bool | None = Field(
        description="Whether the rule runs; false means it exists but does nothing right now."
    )
    sequence: int | None = Field(description="The order Outlook evaluates rules in, lowest first.")
    is_read_only: bool | None = Field(
        description="True for a rule the rules API cannot modify; it still runs."
    )
    has_error: bool | None = Field(description="True when Microsoft 365 marked the rule broken.")
    forwards_to: list[str] = Field(
        description="Addresses this rule forwards a copy of the message to."
    )
    redirects_to: list[str] = Field(
        description="Addresses this rule redirects the message to, with the original sender kept."
    )
    forward_as_attachment_to: list[str] = Field(
        description="Addresses this rule forwards the message to as an attachment."
    )
    moves_to_folder: str | None = Field(
        description="The Graph id of the folder this rule moves the message to; null if none."
    )
    deletes: bool | None = Field(
        description="True when the rule deletes the message, permanently or to Deleted Items."
    )
    marks_as_read: bool | None = Field(
        description="True when the rule marks the message read on arrival."
    )
    stops_processing_more_rules: bool | None = Field(
        description="True when this rule stops Outlook from evaluating any rule after it."
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
    date_time: str | None = Field(
        description=(
            "The moment, in Graph's `{date}T{time}` spelling with no offset; read with "
            + "`time_zone`."
        )
    )
    time_zone: str | None = Field(description="The zone `date_time` is expressed in, usually UTC.")

    @classmethod
    def from_moment(cls, moment: DateTimeTimeZone | None) -> Self | None:
        if moment is None:
            return None
        return cls(date_time=moment.date_time, time_zone=moment.time_zone)


class AutomaticReply(BaseModel):
    status: AutoReplyStatus | None = Field(
        description="`disabled`, `alwaysEnabled`, or `scheduled`."
    )
    external_audience: ExternalAudience | None = Field(
        description=(
            "Who outside the organization receives `external_reply_message`: `none`, "
            + "`contactsOnly`, or `all`."
        )
    )
    scheduled_start: ScheduledMoment | None = Field(
        description="When a `scheduled` reply starts; meaningless unless `status` is `scheduled`."
    )
    scheduled_end: ScheduledMoment | None = Field(description="When a `scheduled` reply stops.")
    internal_reply_message: str | None = Field(
        description="The reply sent to senders inside this organization."
    )
    external_reply_message: str | None = Field(
        description=(
            "The reply sent to senders outside this organization, subject to "
            + "`external_audience`."
        )
    )

    @classmethod
    def from_setting(cls, setting: AutomaticRepliesSetting | None) -> Self:
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
    covers_mailbox_level_forwarding: Literal[False] = Field(
        default=False,
        description=(
            "Always false: Exchange mailbox-level forwarding has no Microsoft Graph property, "
            + "so this does not prove that nobody forwards this mailbox's mail."
        ),
    )
    rules: list[InboxRule] | None = Field(
        description="The Inbox rules, in Graph's order; null when `include` did not ask for them."
    )
    rules_capped: bool | None = Field(
        description=f"True when more than {MAX_RULES} rules exist and the listing stopped short."
    )
    automatic_reply: AutomaticReply | None = Field(
        description="The automatic reply; null only when `include` did not ask for it."
    )
    categories: list[str] | None = Field(
        description="The category display names; null when `include` did not ask for them."
    )
    categories_capped: bool | None = Field(
        description=(
            f"True when more than {MAX_CATEGORIES} categories exist and the listing stopped "
            + "short."
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
                    "Which of the three to read: `all`, `rules`, `replies`, or `categories`."
                )
            ),
        ] = "all",
        client: GraphServiceClient = graph,
    ) -> MailboxSettingsReport:
        return await get_mailbox_settings(client, include=include)
