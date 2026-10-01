from collections.abc import Mapping
from typing import Annotated, Literal, override

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from kiota_abstractions.serialization.serialization_writer import SerializationWriter
from mcp.types import InputRequiredResult
from msgraph.generated.drives.item.items.item.create_link.create_link_post_request_body import (
    CreateLinkPostRequestBody,
)
from msgraph.generated.models.drive_item import DriveItem
from msgraph.generated.models.permission import Permission
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.files import ITEM_HANDLE_SOURCES, item_for_a_question, item_label
from office_365_mcp.shared.handles import DriveFileHandle, DriveFolderHandle, drive_item_handle
from office_365_mcp.shared.notes import write_state_for
from office_365_mcp.shared.seam import (
    WRITE_IDEMPOTENT,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "sharepoint_create_share_link"

STEP_CREATE_LINK = "create_link"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Files.ReadWrite.All",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "item": "sharepoint:///files/b%21SYNTHETICDRIVE0000/01SYNTHETICFILE0000",
    "access": "view",
}

type Access = Literal["view", "edit"]
type Audience = Literal["organization", "anonymous"]

_AGREE = "create"
_DECLINE = "do not create"
_NOTHING_CREATED = "No link was created, and nothing was shared."

_KIND: Mapping[Access, str] = {"view": "a view-only", "edit": "an edit"}

_WHO: Mapping[Audience, str] = {
    "organization": "Anyone in your organization who signs in can use the link.",
    "anonymous": (
        "Anyone who has the link can use it with no sign-in, and that can include people "
        + "outside your organization."
    ),
}

_NO_EXPIRY = "The link does not expire unless your organization sets a limit."

_DESCRIPTION = """\
Creates a sharing link to one file or folder in OneDrive or SharePoint, and returns the web \
address of the link. The user can then give the link to other people. This tool sends the link \
to nobody. To share the item with named people, use sharepoint_invite.

Notes:
- This tool asks the user to agree before it creates anything, every time.
- This call is safe to repeat after a timeout. If this connector already made a link of this \
kind to the item, Microsoft returns that link and makes no second one.
- An administrator can turn off links that work with no sign-in.
"""

_NOT_AN_ITEM_HANDLE = (
    "sharepoint_create_share_link did not get a file handle or a folder handle. A file handle "
    + "looks like sharepoint:///files/{drive_id}/{item_id}, and a folder handle looks like "
    + "sharepoint:///folders/{drive_id}/{item_id}, with both ids percent-encoded. A web address "
    + "is not a handle, and no site name, folder name or file name becomes a handle. "
    + ITEM_HANDLE_SOURCES
    + " No link was created. This same value fails again, so do not retry it."
)

_NO_WEB_ADDRESS = (
    "Microsoft 365 accepted the request, but its answer has no web address for the link. So this "
    + "tool has no link to give you. The link can already exist. You can call this tool again "
    + "one time with the same arguments. If the link exists, Microsoft returns that link and "
    + "makes no second one."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return this file or folder, and this call created no link. The handle "
    + "is well formed, so the argument is not the problem. The item was most probably deleted, or "
    + "somebody moved it to another drive. A handle names the drive as well as the item, so an "
    + "item that moved to another drive needs a new handle. Search again with "
    + "sharepoint_search_files, or browse the folder again with sharepoint_browse_folder, and "
    + "take the `uri` from that new result. The same handle fails the same way, so do not retry "
    + "it."
)


class SharingLink(BaseModel):
    item_uri: str = Field(
        description=(
            "The handle of the file or folder that the link opens. It is the same handle that "
            + "this call received. Pass a file handle to sharepoint_read_file and a folder handle "
            + "to sharepoint_browse_folder."
        )
    )
    web_url: str = Field(
        description=(
            "The link itself, for the user to give to other people. Every person that `audience` "
            + "names can open the item with it. The link does not expire unless the organization "
            + "sets a limit. An owner of the item can remove the link in the sharing settings of "
            + "the item. No tool here removes it."
        )
    )
    access: str | None = Field(
        description=(
            "The kind of link as Microsoft stored it: `view` for read-only, or `edit` for read and "
            + "write. This value comes from the answer and not from the arguments. Null when Graph "
            + "reported none."
        )
    )
    audience: str | None = Field(
        description=(
            "Who can use the link as Microsoft stored it: `organization` or `anonymous`. This "
            + "value comes from the answer and not from the arguments. If it is not the audience "
            + "that the user asked for, tell the user. Null when Graph reported none."
        )
    )


async def create_share_link(
    client: GraphServiceClient,
    *,
    item: str,
    access: Access,
    audience: Audience,
    confirm: Confirm,
) -> SharingLink | InputRequiredResult:
    handle = drive_item_handle(item)
    if handle is None:
        raise ToolError(_NOT_AN_ITEM_HANDLE)

    about = write_state_for(TOOL_NAME, handle.drive_id, handle.item_id, access, audience)
    created: Permission | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors(TOOL_NAME):
        found = await item_for_a_question(client, handle.drive_id, handle.item_id)
        with not_graph():
            answer = await confirm(_question(found, access, audience), about)
        asked = answer if isinstance(answer, InputRequiredResult) else None
        refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with graph_step(STEP_CREATE_LINK):
                created = await (
                    client.drives.by_drive_id(handle.drive_id)
                    .items.by_drive_item_id(handle.item_id)
                    .create_link.post(
                        _KindAndAudienceOnly(type=access, scope=audience),
                        request_configuration=RequestConfiguration[QueryParameters](
                            options=no_retry()
                        ),
                    )
                )

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    return _answer(handle, created)


def _question(item: DriveItem, access: Access, audience: Audience) -> str:
    return f"Create {_KIND[access]} link to {item_label(item)}? {_WHO[audience]} {_NO_EXPIRY}"


class _KindAndAudienceOnly(CreateLinkPostRequestBody):
    @override
    def serialize(self, writer: SerializationWriter) -> None:
        writer.write_str_value("type", self.type)
        writer.write_str_value("scope", self.scope)


def _answer(handle: DriveFileHandle | DriveFolderHandle, created: Permission | None) -> SharingLink:
    link = created.link if created is not None else None
    if link is None or link.web_url is None:
        raise ToolError(_NO_WEB_ADDRESS)
    return SharingLink(
        item_uri=handle.uri, web_url=link.web_url, access=link.type, audience=link.scope
    )


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_AGREE, decline=_DECLINE, nothing_happened=_NOTHING_CREATED)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Create a Sharing Link",
        description=_DESCRIPTION,
        annotations=WRITE_IDEMPOTENT,
    )
    async def sharepoint_create_share_link(
        item: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The file or folder to share. A file handle and a folder handle both work. "
                    + ITEM_HANDLE_SOURCES
                    + " A web address, a path and a name are not handles."
                ),
            ),
        ],
        access: Annotated[
            Literal["view", "edit"],
            Field(
                description=(
                    "What people can do with the link. `view` lets them open and read the item. "
                    + "`edit` also lets them change it. Use the kind that the user asked for. If "
                    + "the user did not say, ask the user."
                ),
            ),
        ],
        ctx: Context,
        audience: Annotated[
            Literal["organization", "anonymous"],
            Field(
                description=(
                    "Who can use the link. `organization`, the default, lets anyone who signs in "
                    + "to the organization of the user use it. `anonymous` lets anyone who has "
                    + "the link use it with no sign-in, and that can include people outside the "
                    + "organization. Use `anonymous` only when the user asks for it."
                ),
            ),
        ] = "organization",
        client: GraphServiceClient = graph,
    ) -> SharingLink | InputRequiredResult:
        return await create_share_link(
            client, item=item, access=access, audience=audience, confirm=a_person_agrees(ctx)
        )
