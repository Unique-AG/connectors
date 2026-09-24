from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Literal, Self

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from msgraph.generated.models.automatic_replies_setting import AutomaticRepliesSetting
from msgraph.generated.models.automatic_replies_status import AutomaticRepliesStatus
from msgraph.generated.models.date_time_time_zone import DateTimeTimeZone
from msgraph.generated.models.external_audience_scope import ExternalAudienceScope
from msgraph.generated.models.mailbox_settings import MailboxSettings
from msgraph.generated.users.item.mailbox_settings.mailbox_settings_request_builder import (
    MailboxSettingsRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry
from office_365_mcp.shared.seam import WRITE_IDEMPOTENT, graph_client_for_caller

TOOL_NAME = "outlook_set_automatic_reply"

STEP_READ = "read_mailbox_settings"
STEP_WRITE = "write_automatic_reply"

GRAPH_PERMISSIONS: tuple[str, ...] = ("MailboxSettings.ReadWrite",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"status": "disabled"}

type SettableStatus = Literal["scheduled", "disabled"]
type ReplyStatus = Literal["disabled", "alwaysEnabled", "scheduled"]
type ExternalAudience = Literal["none", "contactsOnly", "all"]

_SETTINGS_FIELDS: tuple[str, ...] = ("automaticRepliesSetting",)

_SettingsQuery = MailboxSettingsRequestBuilder.MailboxSettingsRequestBuilderGetQueryParameters

_STATUS_TO_WRITE: Mapping[SettableStatus, AutomaticRepliesStatus] = {
    "scheduled": AutomaticRepliesStatus.Scheduled,
    "disabled": AutomaticRepliesStatus.Disabled,
}

_AUDIENCE_TO_WRITE: Mapping[ExternalAudience, ExternalAudienceScope] = {
    "none": ExternalAudienceScope.None_,
    "contactsOnly": ExternalAudienceScope.ContactsOnly,
    "all": ExternalAudienceScope.All,
}

_DESCRIPTION = (
    "Turns the signed-in user's automatic reply (out of office) on for a fixed window, or off."
)

_NO_WINDOW = (
    "outlook_set_automatic_reply refused to schedule an automatic reply without both `start` and "
    + "`end`, so the mailbox was not touched. This tool cannot switch an automatic reply on with "
    + "no end date at all. Microsoft calls that `alwaysEnabled`. It answers every future sender "
    + "until a person turns it off in Outlook, and it is deliberately absent from this tool, "
    + "rather than refused here. Ask the user for a start time and a stop time, then call again "
    + "with both as ISO-8601 date-times. Retrying these arguments will fail identically."
)


class ReplyMoment(BaseModel):
    date_time: str | None = Field(description="The moment, in Graph's combined date-time format.")
    time_zone: str | None = Field(description="The zone that date_time is expressed in.")

    @classmethod
    def from_moment(cls, moment: DateTimeTimeZone | None) -> Self | None:
        if moment is None:
            return None
        return cls(date_time=moment.date_time, time_zone=moment.time_zone)


class AutomaticReplyReport(BaseModel):
    status: ReplyStatus | None = Field(description="disabled, scheduled, or alwaysEnabled.")
    external_audience: ExternalAudience | None = Field(
        description="Who outside the organization receives external_message."
    )
    scheduled_start: ReplyMoment | None = Field(description="When the reply starts.")
    scheduled_end: ReplyMoment | None = Field(description="When the reply stops.")
    internal_message: str | None = Field(
        description="The reply sent to senders inside the organization, or null."
    )
    external_message: str | None = Field(
        description="The reply sent to senders outside the organization, or null."
    )

    @classmethod
    def from_setting(cls, setting: AutomaticRepliesSetting | None) -> Self:
        if setting is None:
            return cls(
                status=None,
                external_audience=None,
                scheduled_start=None,
                scheduled_end=None,
                internal_message=None,
                external_message=None,
            )
        return cls(
            status=_reported_status(setting.status),
            external_audience=_reported_audience(setting.external_audience),
            scheduled_start=ReplyMoment.from_moment(setting.scheduled_start_date_time),
            scheduled_end=ReplyMoment.from_moment(setting.scheduled_end_date_time),
            internal_message=setting.internal_reply_message,
            external_message=setting.external_reply_message,
        )


@dataclass(frozen=True, slots=True)
class ReplyChange:
    status: SettableStatus
    start: str | None = None
    end: str | None = None
    time_zone: str = "UTC"
    internal_message: str | None = None
    external_message: str | None = None
    external_audience: ExternalAudience | None = None

    @property
    def has_no_window(self) -> bool:
        return self.start is None or self.end is None


async def set_automatic_reply(
    client: GraphServiceClient, *, change: ReplyChange
) -> AutomaticReplyReport:
    if change.status == "scheduled" and change.has_no_window:
        raise ToolError(_NO_WINDOW)

    with graph_errors(TOOL_NAME):
        current = await _read_setting(client)
        written = await _write_setting(client, _whole_setting(current, change))
        stored = written if written is not None else await _read_setting(client)

    return AutomaticReplyReport.from_setting(stored)


async def _read_setting(client: GraphServiceClient) -> AutomaticRepliesSetting | None:
    with graph_step(STEP_READ):
        settings = await client.me.mailbox_settings.get(
            request_configuration=RequestConfiguration[_SettingsQuery](
                query_parameters=_SettingsQuery(select=list(_SETTINGS_FIELDS))
            )
        )
    return None if settings is None else settings.automatic_replies_setting


async def _write_setting(
    client: GraphServiceClient, setting: AutomaticRepliesSetting
) -> AutomaticRepliesSetting | None:
    with graph_step(STEP_WRITE):
        updated = await client.me.mailbox_settings.patch(
            MailboxSettings(automatic_replies_setting=setting),
            request_configuration=RequestConfiguration[QueryParameters](options=no_retry()),
        )
    return None if updated is None else updated.automatic_replies_setting


def _whole_setting(
    current: AutomaticRepliesSetting | None, change: ReplyChange
) -> AutomaticRepliesSetting:
    stored = current if current is not None else AutomaticRepliesSetting()
    return AutomaticRepliesSetting(
        status=_STATUS_TO_WRITE[change.status],
        external_audience=_audience(change.external_audience, stored.external_audience),
        scheduled_start_date_time=_moment(
            change.start, change.time_zone, stored.scheduled_start_date_time
        ),
        scheduled_end_date_time=_moment(
            change.end, change.time_zone, stored.scheduled_end_date_time
        ),
        internal_reply_message=_kept(change.internal_message, stored.internal_reply_message),
        external_reply_message=_kept(change.external_message, stored.external_reply_message),
    )


def _audience(
    asked: ExternalAudience | None, stored: ExternalAudienceScope | None
) -> ExternalAudienceScope:
    if asked is not None:
        return _AUDIENCE_TO_WRITE[asked]
    return stored if stored is not None else ExternalAudienceScope.None_


def _moment(
    asked: str | None, time_zone: str, stored: DateTimeTimeZone | None
) -> DateTimeTimeZone | None:
    if asked is None:
        return stored
    return DateTimeTimeZone(date_time=asked, time_zone=time_zone)


def _kept(asked: str | None, stored: str | None) -> str | None:
    return stored if asked is None else asked


def _reported_status(status: AutomaticRepliesStatus | None) -> ReplyStatus | None:
    match status:
        case None:
            return None
        case AutomaticRepliesStatus.Disabled:
            return "disabled"
        case AutomaticRepliesStatus.AlwaysEnabled:
            return "alwaysEnabled"
        case AutomaticRepliesStatus.Scheduled:
            return "scheduled"


def _reported_audience(audience: ExternalAudienceScope | None) -> ExternalAudience | None:
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
        title="Set Automatic Reply",
        description=_DESCRIPTION,
        annotations=WRITE_IDEMPOTENT,
    )
    async def outlook_set_automatic_reply(
        status: Annotated[
            SettableStatus,
            Field(description="scheduled turns the reply on between start and end; disabled off."),
        ],
        start: Annotated[
            str | None,
            Field(description="When the reply starts, ISO-8601. Required with scheduled."),
        ] = None,
        end: Annotated[
            str | None,
            Field(description="When the reply stops, same form as start. Required with scheduled."),
        ] = None,
        time_zone: Annotated[
            str,
            Field(description="The zone start and end are expressed in. Defaults to UTC."),
        ] = "UTC",
        internal_message: Annotated[
            str | None,
            Field(description="The text sent to senders inside the organization."),
        ] = None,
        external_message: Annotated[
            str | None,
            Field(description="The text sent to senders outside the organization."),
        ] = None,
        external_audience: Annotated[
            ExternalAudience | None,
            Field(description="Who outside the organization is answered at all."),
        ] = None,
        client: GraphServiceClient = graph,
    ) -> AutomaticReplyReport:
        return await set_automatic_reply(
            client,
            change=ReplyChange(
                status=status,
                start=start,
                end=end,
                time_zone=time_zone,
                internal_message=internal_message,
                external_message=external_message,
                external_audience=external_audience,
            ),
        )
