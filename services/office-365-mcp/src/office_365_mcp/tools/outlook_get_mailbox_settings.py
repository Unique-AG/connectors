from collections.abc import Mapping
from typing import Annotated, Literal, Self

import httpx
from fastmcp import FastMCP
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.automatic_replies_setting import AutomaticRepliesSetting
from msgraph.generated.models.automatic_replies_status import AutomaticRepliesStatus
from msgraph.generated.models.date_time_time_zone import DateTimeTimeZone
from msgraph.generated.models.external_audience_scope import ExternalAudienceScope
from msgraph.generated.models.locale_info import LocaleInfo
from msgraph.generated.models.mailbox_settings import MailboxSettings
from msgraph.generated.models.message_rule import MessageRule
from msgraph.generated.models.outlook_category import OutlookCategory
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

from office_365_mcp.graph_client import (
    MAX_SCANNED_ITEMS,
    CollectedItems,
    collect_pages,
    graph_errors,
    graph_step,
)
from office_365_mcp.shared.calendar import WorkingHoursSummary
from office_365_mcp.shared.handles import MailFolderHandle
from office_365_mcp.shared.rules import InboxRule
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

_INBOX_FOLDER = "inbox"

_RULE_FIELDS: tuple[str, ...] = (
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

_REPLY_FIELDS: tuple[str, ...] = ("automaticRepliesSetting",)

_CATEGORY_FIELDS: tuple[str, ...] = ("displayName",)

_RulesQuery = MessageRulesRequestBuilder.MessageRulesRequestBuilderGetQueryParameters
_SettingsQuery = MailboxSettingsRequestBuilder.MailboxSettingsRequestBuilderGetQueryParameters
_CategoriesQuery = MasterCategoriesRequestBuilder.MasterCategoriesRequestBuilderGetQueryParameters

type Include = Literal["all", "rules", "replies", "categories", "preferences"]

type AutoReplyStatus = Literal["disabled", "alwaysEnabled", "scheduled"]
type ExternalAudience = Literal["none", "contactsOnly", "all"]

_DESCRIPTION = """\
Reads the settings of the signed-in user's own mailbox. The answer holds the inbox rules with \
their conditions, exceptions, and actions. It also holds the automatic reply, the category names, \
the time zone, the working hours, the language, and the archive folder. If this deployment exposes \
outlook_set_automatic_reply, that tool changes the automatic reply.

Notes:
- This tool cannot see Exchange mailbox-level forwarding. A rule list with no forward action \
does not prove that nobody forwards this mailbox's mail.
- If this deployment exposes outlook_list_categories, that tool also gives the color of each \
category.
"""


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


class Language(BaseModel):
    locale: str | None = Field(
        description=(
            "The locale of the mailbox owner. It has a 2-letter language code and a 2-letter "
            + "country or region code, for example `en-US`. Null when Graph reports none."
        )
    )
    display_name: str | None = Field(
        description=(
            "The name of the locale in natural language, for example `English (United States)`. "
            + "Null when Graph reports none."
        )
    )

    @classmethod
    def from_locale_info(cls, info: LocaleInfo | None) -> Self | None:
        if info is None:
            return None
        return cls(locale=info.locale, display_name=info.display_name)


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
        description="True when more rules exist and the listing stopped short."
    )
    automatic_reply: AutomaticReply | None = Field(
        description="The automatic reply; null only when `include` did not ask for it."
    )
    categories: list[str] | None = Field(
        description="The category display names; null when `include` did not ask for them."
    )
    categories_capped: bool | None = Field(
        description="True when more categories exist and the listing stopped short."
    )
    time_zone: str | None = Field(
        description=(
            "The default time zone of the mailbox, in the spelling that the administrator chose. "
            + "It is a Windows name such as `Pacific Standard Time`, or an IANA name. Null when "
            + "`include` did not ask for it, or when Graph reports none."
        )
    )
    working_hours: WorkingHoursSummary | None = Field(
        description=(
            "The days and the hours in which the mailbox owner works. Null when `include` did "
            + "not ask for them, or when Graph reports none."
        )
    )
    language: Language | None = Field(
        description=(
            "The preferred language and the country or region of the mailbox owner. Null when "
            + "`include` did not ask for it, or when Graph reports none."
        )
    )
    archive_folder_uri: str | None = Field(
        description=(
            "The handle of the archive folder of the mailbox, `outlook:///folders/{id}`. If this "
            + "deployment exposes outlook_move_mail, pass this handle as `folder_ref` to that "
            + "tool. Null when `include` did not ask for it, or when Graph reports none."
        )
    )


async def get_mailbox_settings(
    client: GraphServiceClient, *, include: Include = "all"
) -> MailboxSettingsReport:
    wants_rules = include in ("all", "rules")
    wants_replies = include in ("all", "replies")
    wants_categories = include in ("all", "categories")
    wants_preferences = include in ("all", "preferences")
    wants_settings = wants_replies or wants_preferences
    settings_select = None if wants_preferences else _REPLY_FIELDS

    with graph_errors(TOOL_NAME):
        rules = await _inbox_rules(client) if wants_rules else None
        settings = await _mailbox_settings(client, settings_select) if wants_settings else None
        categories = await _categories(client) if wants_categories else None

    reply = None if settings is None else settings.automatic_replies_setting
    preferences = settings if wants_preferences else None
    return MailboxSettingsReport(
        rules=None if rules is None else [InboxRule.from_rule(rule) for rule in rules.items],
        rules_capped=None if rules is None else rules.capped,
        automatic_reply=AutomaticReply.from_setting(reply) if wants_replies else None,
        categories=(
            None
            if categories is None
            else [_category_name(category) for category in categories.items]
        ),
        categories_capped=None if categories is None else categories.capped,
        time_zone=None if preferences is None else preferences.time_zone,
        working_hours=(
            None
            if preferences is None
            else WorkingHoursSummary.from_working_hours(preferences.working_hours)
        ),
        language=None if preferences is None else Language.from_locale_info(preferences.language),
        archive_folder_uri=(
            None
            if preferences is None or not preferences.archive_folder
            else MailFolderHandle(preferences.archive_folder).uri
        ),
    )


async def _inbox_rules(client: GraphServiceClient) -> CollectedItems[MessageRule]:
    with graph_step(STEP_RULES):
        first_page = await client.me.mail_folders.by_mail_folder_id(
            _INBOX_FOLDER
        ).message_rules.get(
            request_configuration=RequestConfiguration[_RulesQuery](
                query_parameters=_RulesQuery(select=list(_RULE_FIELDS))
            )
        )
        assert first_page is not None, "Graph answered a rule listing with no collection"
        return await collect_pages(first_page, client, limit=MAX_SCANNED_ITEMS)


async def _mailbox_settings(
    client: GraphServiceClient, select: tuple[str, ...] | None
) -> MailboxSettings | None:
    with graph_step(STEP_SETTINGS):
        return await client.me.mailbox_settings.get(
            request_configuration=RequestConfiguration[_SettingsQuery](
                query_parameters=_SettingsQuery(select=None if select is None else list(select))
            )
        )


async def _categories(client: GraphServiceClient) -> CollectedItems[OutlookCategory]:
    with graph_step(STEP_CATEGORIES):
        first_page = await client.me.outlook.master_categories.get(
            request_configuration=RequestConfiguration[_CategoriesQuery](
                query_parameters=_CategoriesQuery(select=list(_CATEGORY_FIELDS))
            )
        )
        assert first_page is not None, "Graph answered a category listing with no collection"
        return await collect_pages(first_page, client, limit=MAX_SCANNED_ITEMS)


def _category_name(category: OutlookCategory) -> str:
    assert category.display_name is not None, "Graph returned a category with no display name"
    return category.display_name


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
                    "The part of the mailbox settings to read: `all`, `rules`, `replies`, "
                    + "`categories`, or `preferences`. The `preferences` part is the time zone, "
                    + "the working hours, the language, and the archive folder."
                )
            ),
        ] = "all",
        client: GraphServiceClient = graph,
    ) -> MailboxSettingsReport:
        return await get_mailbox_settings(client, include=include)
