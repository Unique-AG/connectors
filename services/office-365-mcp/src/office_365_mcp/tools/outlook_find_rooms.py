from collections.abc import Callable, Mapping
from typing import Annotated, Self

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.generated.models.room import Room
from msgraph.generated.models.room_collection_response import RoomCollectionResponse
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import MAX_SCANNED_ITEMS, collect_pages, graph_errors
from office_365_mcp.shared.mail import ONE_ADDRESS
from office_365_mcp.shared.odata import spelled
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "outlook_find_rooms"

STEP = "rooms"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Place.Read.All",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {}

_AGAIN = "If you call this tool again with the same arguments, the call will fail the same way."

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not find what this call asked for, so this tool listed no room. When the "
    + "call names a `room_list`, Microsoft found no room list at that address. Ask the user for "
    + f"the address of the room list, or call this tool again without `room_list`. {_AGAIN}"
)

_DESCRIPTION = """\
Lists the meeting rooms of the organization of the signed-in user. Each row gives the address, \
the capacity, the building, the floor, and the equipment of one room. outlook_create_event books \
a room, and outlook_check_availability shows whether a room is free.

Notes:
- Show the rooms to the user and let the user choose. Do not book a room that the user did not \
choose.
- Microsoft lists rooms only after an administrator turns on buildings in the Places settings. \
An empty list does not prove that the organization has no room.
"""

_NOT_ONE_ADDRESS = (
    "outlook_find_rooms takes one SMTP address in `room_list`, such as `building2@example.com`. "
    + f"The name of a room list is not its address. This tool read nothing. {_AGAIN}"
)


class RoomSummary(BaseModel):
    display_name: str | None = Field(
        description=(
            "The name of the room, as Microsoft 365 reports it, such as `Conf Room 100`. Two "
            + "rooms can have the same name. The value is null when Microsoft 365 reports no name."
        )
    )
    address: str | None = Field(
        description=(
            "The SMTP address of the mailbox of the room. Pass it in `room_addresses` to "
            + "outlook_create_event, or in `addresses` to outlook_check_availability. The value "
            + "is null when Microsoft 365 reports no address."
        )
    )
    capacity: int | None = Field(
        description=(
            "The number of people that the room holds, as Microsoft 365 reports it. The value is "
            + "null when Microsoft 365 reports no capacity."
        )
    )
    building: str | None = Field(
        description=(
            "The name or the number of the building that the room is in. The value is null when "
            + "Microsoft 365 reports no building."
        )
    )
    floor_number: int | None = Field(
        description=(
            "The number of the floor that the room is on. The value is null when Microsoft 365 "
            + "reports no floor number."
        )
    )
    floor_label: str | None = Field(
        description=(
            "A label for the floor that the room is on, such as `P`. The value is null when "
            + "Microsoft 365 reports no floor label."
        )
    )
    label: str | None = Field(
        description=(
            "A label for the room, such as a number or a name. The value is null when Microsoft "
            + "365 reports no label."
        )
    )
    nickname: str | None = Field(
        description=(
            "A short name for the room, such as `conf room`. The value is null when Microsoft 365 "
            + "reports no nickname."
        )
    )
    booking_type: str | None = Field(
        description=(
            "How people can use the room, as Microsoft names it. `standard` means that people can "
            + "book the room. `reserved` means that the room is first come, first served, and "
            + "nobody can book it. `unknown` means that Microsoft 365 does not say. The value is "
            + "null when Microsoft 365 reports no type."
        )
    )
    is_wheel_chair_accessible: bool | None = Field(
        description=(
            "True when a person in a wheelchair can get into the room. False when the room is "
            + "not accessible by wheelchair. Null when Microsoft 365 does not say."
        )
    )
    tags: list[str] = Field(
        description=(
            "Other features of the room, such as the view or the furniture, as Microsoft 365 "
            + "reports them. The list is empty when Microsoft 365 reports no feature."
        )
    )
    audio_device_name: str | None = Field(
        description=(
            "The name of the audio device in the room. The value is null when Microsoft 365 "
            + "reports no audio device."
        )
    )
    video_device_name: str | None = Field(
        description=(
            "The name of the video device in the room. The value is null when Microsoft 365 "
            + "reports no video device."
        )
    )
    display_device_name: str | None = Field(
        description=(
            "The name of the display device in the room, such as a screen. The value is null "
            + "when Microsoft 365 reports no display device."
        )
    )
    teams_enabled_state: str | None = Field(
        description=(
            "Whether the room is set up for Microsoft Teams, as Microsoft names it: `enabled`, "
            + "`disabled`, or `unknown`. The value is null when Microsoft 365 does not say."
        )
    )

    @classmethod
    def from_room(cls, room: Room) -> Self:
        return cls(
            display_name=room.display_name,
            address=room.email_address,
            capacity=room.capacity,
            building=room.building,
            floor_number=room.floor_number,
            floor_label=room.floor_label,
            label=room.label,
            nickname=room.nickname,
            booking_type=spelled(room.booking_type),
            is_wheel_chair_accessible=room.is_wheel_chair_accessible,
            tags=list(room.tags or []),
            audio_device_name=room.audio_device_name,
            video_device_name=room.video_device_name,
            display_device_name=room.display_device_name,
            teams_enabled_state=spelled(room.teams_enabled_state),
        )


class Rooms(BaseModel):
    rooms: list[RoomSummary] = Field(
        description=(
            "The rooms that matched, in the order that Graph returns them. The list is empty when "
            + "no room matched. Read `capped` before you report that the list is complete."
        )
    )
    capped: bool = Field(
        description=(
            "True when the listing stopped early, so more rooms can remain. The listing stops "
            + f"after `limit` rooms that match, or after it reads {MAX_SCANNED_ITEMS} rooms. If "
            + "the answer holds fewer than `limit` rooms, a higher `limit` cannot help. Then name "
            + "a `room_list`."
        )
    )


async def find_rooms(
    client: GraphServiceClient,
    *,
    room_list: str | None = None,
    min_capacity: int | None = None,
    limit: int,
) -> Rooms:
    assert 1 <= limit <= MAX_SCANNED_ITEMS, (
        f"limit must be within 1..{MAX_SCANNED_ITEMS}, got {limit}"
    )
    wanted_list = None if room_list is None else room_list.strip()
    if wanted_list is not None and ONE_ADDRESS.match(wanted_list) is None:
        raise ToolError(_NOT_ONE_ADDRESS)

    with graph_errors(TOOL_NAME, step=STEP):
        first_page = await _first_page(client, wanted_list)
        assert first_page is not None, "Graph answered a room listing with no collection"
        collected = await collect_pages(
            first_page,
            client,
            limit=limit,
            matches=None if min_capacity is None else _holds_at_least(min_capacity),
        )

    return Rooms(
        rooms=[RoomSummary.from_room(room) for room in collected.items],
        capped=collected.capped,
    )


async def _first_page(
    client: GraphServiceClient, room_list: str | None
) -> RoomCollectionResponse | None:
    if room_list is None:
        return await client.places.graph_room.get()
    return await client.places.by_place_id(room_list).graph_room_list.rooms.get()


def _holds_at_least(seats: int) -> Callable[[Room], bool]:
    def holds(room: Room) -> bool:
        return room.capacity is not None and room.capacity >= seats

    return holds


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Find Rooms",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def outlook_find_rooms(
        room_list: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The SMTP address of one room list, to list only the rooms in that list. "
                    + "Microsoft finds a room list only by its address, not by its name. Take the "
                    + "address from the user. Omit it to list every room of the organization."
                ),
            ),
        ] = None,
        min_capacity: Annotated[
            int | None,
            Field(
                ge=1,
                description=(
                    "The smallest capacity that a room must have, such as `8` for a meeting of "
                    + "eight people. This connector removes the smaller rooms after Microsoft 365 "
                    + "returns the list. It also removes each room with no capacity. Omit it to "
                    + "list rooms of every size."
                ),
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_SCANNED_ITEMS,
                description=(
                    f"How many rooms to return, at most {MAX_SCANNED_ITEMS}. The answer is the "
                    + "whole result of this call. A second call with the same `limit` returns the "
                    + "same rooms, not the next rooms. Read `capped` before you raise `limit`."
                ),
            ),
        ] = 50,
        client: GraphServiceClient = graph,
    ) -> Rooms:
        return await find_rooms(client, room_list=room_list, min_capacity=min_capacity, limit=limit)
