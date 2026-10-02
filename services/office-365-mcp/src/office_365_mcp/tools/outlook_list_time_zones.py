from collections.abc import Mapping
from typing import Annotated, Literal, Self

import httpx
from fastmcp import FastMCP
from kiota_abstractions.method import Method
from kiota_abstractions.request_information import RequestInformation
from msgraph.generated.models.o_data_errors.o_data_error import ODataError
from msgraph.generated.models.time_zone_information import TimeZoneInformation
from msgraph.generated.users.item.outlook.supported_time_zones.supported_time_zones_get_response import (  # noqa: E501
    SupportedTimeZonesGetResponse,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import MAX_SCANNED_ITEMS, collect_pages, graph_errors
from office_365_mcp.shared import identity
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "outlook_list_time_zones"

STEP = "time_zones"

GRAPH_PERMISSIONS: tuple[str, ...] = (identity.GRAPH_PERMISSION,)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {}

type Standard = Literal["windows", "iana"]

_SDK_SPELLING = "TimeZoneStandard='{TimeZoneStandard}'"
_DOCUMENTED_SPELLING = "TimeZoneStandard=microsoft.graph.timeZoneStandard'{TimeZoneStandard}'"

_DESCRIPTION = """\
Lists the time zones that the mailbox server of the signed-in user supports, as Windows names or \
as IANA names. Each row has a zone name and a display label. This tool only reads. It changes \
nothing.

Notes:
- A tool that lists or reads events, event occurrences, or reminders takes only IANA names in \
`time_zone`. This tool lists Windows names by default. For a tool that takes only IANA names, \
set `standard` to `iana`.
- Every other tool that takes a zone name sends it to Microsoft as written. Microsoft accepts \
either spelling.
- Find the row that matches the place that the user named. Do not guess a zone name. An \
`Etc/GMT+N` name is N hours behind UTC, not ahead of it.
"""


class TimeZone(BaseModel):
    alias: str = Field(
        description=(
            "The zone name, exactly as Graph wrote it. Pass it word for word to a tool that "
            + "takes a time zone name. Do not change its case or its spelling."
        )
    )
    display_name: str | None = Field(
        description=(
            "A label for a person to read, such as `(UTC-10:00) Aleutian Islands`. In an IANA "
            + "row, it repeats the zone name. Do not pass it as a zone name. Null if Graph "
            + "sent none."
        )
    )

    @classmethod
    def from_information(cls, zone: TimeZoneInformation) -> Self:
        assert zone.alias is not None, "Graph listed a time zone with no alias"
        return cls(alias=zone.alias, display_name=zone.display_name)


class TimeZones(BaseModel):
    time_zones: list[TimeZone] = Field(
        description=(
            "The time zones that the mailbox server supports, in the order that Graph returned "
            + "them. The list is empty if Graph returned none."
        )
    )
    capped: bool = Field(
        description=(
            "True if the listing stopped early with more time zones remaining. Then `time_zones` "
            + "can lack a zone that the mailbox server supports."
        )
    )


async def list_time_zones(
    client: GraphServiceClient, *, standard: Standard = "windows"
) -> TimeZones:
    with graph_errors(TOOL_NAME, step=STEP):
        first_page = await _first_page(client, standard)
        assert first_page is not None, "Graph answered a time zone listing with no collection"
        collected = await collect_pages(first_page, client, limit=MAX_SCANNED_ITEMS)

    return TimeZones(
        time_zones=[TimeZone.from_information(zone) for zone in collected.items],
        capped=collected.capped,
    )


async def _first_page(
    client: GraphServiceClient, standard: Standard
) -> SupportedTimeZonesGetResponse | None:
    if standard == "windows":
        return await client.me.outlook.supported_time_zones.get()
    builder = client.me.outlook.supported_time_zones_with_time_zone_standard("Iana")
    template = builder.url_template.replace(_SDK_SPELLING, _DOCUMENTED_SPELLING)
    assert template != builder.url_template, (
        "The SDK spells the time zone standard in a form that this tool cannot rewrite."
    )
    request = RequestInformation(Method.GET, template, builder.path_parameters)
    request.headers.try_add("Accept", "application/json")
    return await client.request_adapter.send_async(  # pyright: ignore[reportUnknownMemberType]
        request, SupportedTimeZonesGetResponse, {"XXX": ODataError}
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="List Time Zones",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def outlook_list_time_zones(
        standard: Annotated[
            Standard,
            Field(
                description=(
                    "The spelling of the zone names. `windows` lists Windows names, such as "
                    + "`Aleutian Standard Time`. `iana` lists IANA names, such as "
                    + "`US/Aleutian`. The default is `windows`."
                )
            ),
        ] = "windows",
        client: GraphServiceClient = graph,
    ) -> TimeZones:
        return await list_time_zones(client, standard=standard)
