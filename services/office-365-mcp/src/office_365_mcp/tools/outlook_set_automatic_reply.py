"""`outlook_set_automatic_reply` — the out-of-office, on for a bounded window or off, never open.

**`alwaysEnabled` is deliberately not offered. That absence is the shape of this tool.** It is
Graph's third status, and it sets a reply with no end date. Every future sender is answered, the
user's colleagues and strangers alike, until a human notices and turns it off in Outlook. That
outlives the conversation that asked for it, including for whoever asked: they get the reply
back the next time they write. So `scheduled` requires both `start` and `end`, and is refused
without them. The only other status here is `disabled`.

**This tool reads the whole `automaticRepliesSetting` first, then sends it back whole. It never
sends only the properties that changed.** Microsoft's two PATCH documents show OPPOSITE merge
behavior for a nested complex type. `user-update-mailboxsettings` Example 1
(https://learn.microsoft.com/en-us/graph/api/user-update-mailboxsettings) sends
`automaticRepliesSetting` carrying `status` and the two dates alone. Its 200 response still
carries `externalAudience: all` and both reply messages: what was left out survived.
`messagerule-update` (https://learn.microsoft.com/en-us/graph/api/messagerule-update) sends
`actions` carrying `markImportance` alone, at a rule whose action was `forwardTo`. The response's
`actions` is `markImportance` alone: what was left out is gone. Neither page says which of the
two behaviors this endpoint's nested object follows. Sending every property, each taken from the
argument that named it or from the mailbox's current value, makes the two behaviors produce the
same object. So this tool never has to answer that question. Without this, an `external_message`
of None either re-broadcasts whatever text was last in the mailbox, or silently erases it, and
this tool cannot tell which one happened.

**An omitted message keeps the text the mailbox already holds. There is no way to clear one.**
That is the honest reading of the paragraph above, and it is also the only one the SDK can
express. Kiota's JSON writer drops a property whose value is None, instead of writing an
explicit null (`kiota_serialization_json/json_serialization_writer.py`). So "send nothing there"
and "send null there" are the same bytes. `disabled` is how an automatic reply stops. The text
left behind in the mailbox is inert while the status says so, and this tool reports it either
way, instead of answering that there is none.

**The answer is read off Graph's own response to the write, never off the arguments.**
Microsoft's Example 1 sends `scheduledStartDateTime` as `2016-03-20T18:00:00.0000000` in UTC,
and the response returns `2016-03-20T02:00:00.0000000` in UTC. Exchange stored a different
moment from the one the request named. A tool that echoes its arguments reports a window the
mailbox does not have. The user is then away at the wrong hours, with a transcript that says
otherwise.

**`no_retry()` on the PATCH.** The SDK retries every verb on 429, 503 and 504, and
`GRAPH_MAX_RETRIES` defaults to 3. This write is idempotent, so the risk is not double
application. The risk is that a retried PATCH is answered by a different response from the one
that was applied. This tool's whole promise is that its answer is what the mailbox now holds.
"""

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

# Switching the reply off, which is the one call that needs no other argument and still reaches
# Graph. A `scheduled` example without both dates is refused before any request.
GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"status": "disabled"}

# Microsoft's own spellings, so a value here matches the documentation, the admin center and
# what outlook_get_mailbox_settings reports, instead of a vocabulary invented in this file.
type SettableStatus = Literal["scheduled", "disabled"]
type ReplyStatus = Literal["disabled", "alwaysEnabled", "scheduled"]
type ExternalAudience = Literal["none", "contactsOnly", "all"]

# The one property of the nine this tool reads and writes. Microsoft documents `mailboxSettings`
# as requiring `$select`. Asking for the rest drags in a working-hours block that nothing here
# reports, and that nothing here can overwrite.
_SETTINGS_FIELDS: tuple[str, ...] = ("automaticRepliesSetting",)

# Bound rather than aliased with `type`: this is spelled as the query parameters' constructor as
# well as `RequestConfiguration`'s argument, and a `TypeAliasType` is not callable.
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

_DESCRIPTION = """\
Turn the signed-in user's automatic reply (out of office) ON for a fixed window, or OFF. THIS \
CHANGES THE MAILBOX, and what it changes is what Microsoft 365 sends to other people. While the \
reply is on, everyone who emails this user gets `internal_message` back automatically, and \
senders outside the organization get `external_message` instead, as far as `external_audience` \
allows. That text is disclosed to whoever writes, including strangers and spam. Treat dates \
away from home, a deputy's address or a phone number in it as published. Pass `status: \
"disabled"` to turn an automatic reply off. That is the only way to stop one through this \
connector, and it is a whole call, not an argument on something else. `status: "scheduled"` \
REQUIRES both `start` and `end`. A reply with no end date is not offered here at all, because it \
answers every future sender long after the conversation that set it is over. Omitting \
`internal_message` or `external_message` keeps the text already in the mailbox, and re-sends \
it. Read the answer, which reports the text now going out, instead of assuming that an omitted \
message means none. The answer is read back from Microsoft's own response, so a window in it \
that differs from `start` and `end` is Exchange's own conversion, and is the truth about when \
the user is away.\
"""

_NO_WINDOW = (
    "outlook_set_automatic_reply refused to schedule an automatic reply without both `start` and "
    + "`end`, so the mailbox was not touched. This tool cannot switch an automatic reply on with "
    + "no end date at all. Microsoft calls that `alwaysEnabled`. It answers every future sender "
    + "until a person turns it off in Outlook, and it is deliberately absent from this tool, "
    + "rather than refused here. Ask the user for a start time and a stop time, then call again "
    + "with both as ISO-8601 date-times. Retrying these arguments will fail identically."
)


class ReplyMoment(BaseModel):
    """One end of the window, as the date and the zone Microsoft 365 reports it in."""

    date_time: str | None = Field(
        description=(
            "The moment, in Graph's own combined `{date}T{time}` spelling, carrying no offset. "
            + "Read it against `time_zone`. This is what Microsoft stored, which is not always "
            + "what was sent: Exchange converts, and the converted value is the one the mailbox "
            + "acts on. Null when Microsoft recorded none."
        )
    )
    time_zone: str | None = Field(
        description=(
            "The zone `date_time` is expressed in, usually `UTC`. Never assume it: a window read "
            + "in the wrong zone is off by hours, and reports the user as back at their desk "
            + "while the mailbox is still answering for them."
        )
    )

    @classmethod
    def from_moment(cls, moment: DateTimeTimeZone | None) -> Self | None:
        if moment is None:
            return None
        return cls(date_time=moment.date_time, time_zone=moment.time_zone)


class AutomaticReplyReport(BaseModel):
    """The automatic reply as Microsoft 365 now holds it, read off its answer to this write.

    Not one field of this is built from the arguments. A tool that echoes them reports a
    success in exactly the case worth catching: the one where Exchange accepted the request and
    stored something other than what it was asked for.
    """

    status: ReplyStatus | None = Field(
        description=(
            "`disabled`: nothing is sent. `scheduled`: senders are answered between "
            + "`scheduled_start` and `scheduled_end`, and at no other time. `alwaysEnabled`: "
            + "every sender is answered with no end date. This tool cannot set that, so it means "
            + "the mailbox already held that status, and this call did not change it. Null when "
            + "Microsoft reported no status. Anything but `disabled` means the messages below go "
            + "out to people."
        )
    )
    external_audience: ExternalAudience | None = Field(
        description=(
            "Who outside this organization receives `external_message`. `none`: nobody, so only "
            + "colleagues are answered. `contactsOnly`: only senders already in the user's "
            + "contacts. `all`: every outside sender, strangers and spam included. Null when "
            + "Microsoft did not say."
        )
    )
    scheduled_start: ReplyMoment | None = Field(
        description=(
            "When the reply starts. Microsoft reports a value here whatever the status is, so it "
            + "means nothing unless `status` is `scheduled`. A date on a `disabled` reply is "
            + "leftover, not evidence. Compare it with the `start` argument. If there is a "
            + "difference, report it: this is the moment the mailbox acts on."
        )
    )
    scheduled_end: ReplyMoment | None = Field(
        description=(
            "When the reply stops, on the same terms as `scheduled_start`. This is the whole of "
            + "what stops an automatic reply on its own. Nothing else expires it."
        )
    )
    internal_message: str | None = Field(
        description=(
            "The reply now sent to senders inside this organization, as Microsoft stored it: "
            + "usually HTML, not the plain text that was sent. Null when the mailbox holds none. "
            + "A value here that nobody passed in this call is text the mailbox already held, "
            + "sent again automatically. Say so, instead of presenting it as new."
        )
    )
    external_message: str | None = Field(
        description=(
            "The reply now sent to senders outside this organization, subject to "
            + "`external_audience`. Read it for what it discloses to strangers: dates away from "
            + "home, a deputy's address, a phone number. Do not read it only for whether a reply "
            + "is on. Null when the mailbox holds none."
        )
    )

    @classmethod
    def from_setting(cls, setting: AutomaticRepliesSetting | None) -> Self:
        """Every field null for a mailbox Microsoft answered with no setting at all, which says
        "Microsoft told us nothing" and never "the reply is off"."""
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
    """What to write, separately from how it reaches Graph. A None here keeps the mailbox's own."""

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
    """`change` written onto the whole `automaticRepliesSetting`, reported as Microsoft kept it."""
    if change.status == "scheduled" and change.has_no_window:
        raise ToolError(_NO_WINDOW)

    with graph_errors(TOOL_NAME):
        current = await _read_setting(client)
        written = await _write_setting(client, _whole_setting(current, change))
        # A PATCH Microsoft answered with no setting on it leaves the promise above unkept, so the
        # setting is read again rather than the arguments reported in its place.
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
    """Every property of the setting, from the argument that named it or from the mailbox.

    A fresh object rather than the one that was read: `current` is the caller's, and the merge
    behavior this defends against is exactly the kind of thing an in-place edit hides.
    """
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
    """`none` when neither the caller nor the mailbox says, because it discloses the least: the
    reply then reaches colleagues only, and nobody outside the organization."""
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
            Field(
                description=(
                    "`scheduled` switches the automatic reply ON between `start` and `end`, both "
                    + "of which are then required. `disabled` switches it OFF, and is the only "
                    + "way to stop one through this connector. There is no third value: "
                    + "Microsoft's `alwaysEnabled`, an automatic reply with no end date, is not "
                    + "offered here."
                )
            ),
        ],
        start: Annotated[
            str | None,
            Field(
                description=(
                    "When the reply starts, as an ISO-8601 date-time without an offset, for "
                    + "example `2026-09-01T08:00:00`. Read against `time_zone`. Required with "
                    + "`scheduled`. Microsoft accepts a future range only. Omit with `disabled`, "
                    + "where a schedule is inert. Leaving it out keeps whatever dates the mailbox "
                    + "already had."
                )
            ),
        ] = None,
        end: Annotated[
            str | None,
            Field(
                description=(
                    "When the reply stops, on the same terms as `start`, and required with "
                    + "`scheduled`. This is the whole of what turns the reply off by itself, so "
                    + "ask the user for a real date rather than a distant one standing in for "
                    + "'until I say otherwise'."
                )
            ),
        ] = None,
        time_zone: Annotated[
            str,
            Field(
                description=(
                    "The zone `start` and `end` are expressed in: a Windows or IANA name such as "
                    + "`UTC`, `W. Europe Standard Time` or `Europe/Zurich`. Defaults to `UTC`, so "
                    + "a local time passed without this is written as a UTC time and the user is "
                    + "away at the wrong hours. Microsoft can convert and store a different "
                    + "spelling. The answer reports what it stored."
                )
            ),
        ] = "UTC",
        internal_message: Annotated[
            str | None,
            Field(
                description=(
                    "The text sent automatically to senders inside the organization. Plain text "
                    + "or HTML. Outlook stores and shows it as HTML. Omit to keep the text the "
                    + "mailbox already holds. That text is then re-sent to everyone who writes, "
                    + "so omitting this is not the same as sending nothing."
                )
            ),
        ] = None,
        external_message: Annotated[
            str | None,
            Field(
                description=(
                    "The text sent automatically to senders OUTSIDE the organization, as far as "
                    + "`external_audience` allows. Anyone who emails the user can read it, "
                    + "strangers and spam included, so keep travel dates, home arrangements and "
                    + "personal numbers out of it. Omit to keep the text already in the mailbox."
                )
            ),
        ] = None,
        external_audience: Annotated[
            ExternalAudience | None,
            Field(
                description=(
                    "Who outside the organization is answered at all. `none`: nobody, so only "
                    + "colleagues get a reply. `contactsOnly`: only senders in the user's "
                    + "contacts. `all`: every outside sender. Omit to keep what the mailbox is "
                    + "already set to, which can well be `all`. The answer reports what is in "
                    + "force."
                )
            ),
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
