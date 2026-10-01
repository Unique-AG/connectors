from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, cast

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.method import Method
from kiota_abstractions.request_information import RequestInformation
from msgraph.generated.models.copy_notebook_model import CopyNotebookModel
from msgraph.generated.models.o_data_errors.o_data_error import ODataError
from msgraph.generated.users.item.onenote.notebooks.get_notebook_from_web_url import (
    get_notebook_from_web_url_post_request_body as _post_body,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors
from office_365_mcp.shared.handles import (
    OnenoteNotebookHandle,
    onenote_notebook_handle,
    onenote_page_handle,
    onenote_section_group_handle,
    onenote_section_handle,
)
from office_365_mcp.shared.notes import client_url_of, onenote_root, web_url_of
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "onenote_find_notebook_from_url"

STEP_NOTEBOOK_FROM_URL = "notebook_from_url"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Notes.Read",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "web_url": "https://onenote.example.invalid/notebooks/synthetic-notebook"
}

_DESCRIPTION = """\
Resolves a OneNote web address into a notebook handle. It asks Microsoft directly. It does not \
search or guess. A page's or a section's address resolves to the notebook that holds it. \
onenote_list_recent_notebooks rows carry no handle. Pass their `web_url` here to get one. Pass \
`group` for the address of a notebook that a Microsoft 365 group or team owns.\
"""

_OWN_NOTEBOOK_HANDLE_NOT_A_WEB_ADDRESS = (
    "onenote_find_notebook_from_url takes a web address or Microsoft's own `onenote:` client "
    + "address, not one of this connector's own onenote:/// handles. This value is already a "
    + "notebook handle: it needs no resolving at all, pass it straight to onenote_list_sections. "
    + "This same value fails again, so do not retry it."
)

_OWN_OTHER_HANDLE_NOT_A_WEB_ADDRESS = (
    "onenote_find_notebook_from_url takes a web address or Microsoft's own `onenote:` client "
    + "address, not one of this connector's own onenote:/// handles. This value is a page, "
    + "section or section group handle, not a notebook one, and this tool does not resolve it: "
    + "use onenote_list_pages to work with a page handle, or onenote_list_notebooks to find the "
    + "notebook a section or section group belongs to. This same value fails again, so do not "
    + "retry it."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 found no notebook at this address: the address names no notebook this user "
    + "can reach. It may be misspelled, point at something Microsoft does not treat as a "
    + "notebook, or name a notebook this user has no access to. Take a fresh `web_url` from "
    + "onenote_list_notebooks or onenote_list_recent_notebooks, or from a page, section or "
    + "notebook this connector already read, and copy it exactly. This same address fails "
    + "again, so do not retry it. If this call named a `group`, that group most likely does not "
    + "own the notebook. A call with another `group`, or with none, can still work."
)


class FoundNotebook(BaseModel):
    uri: str = Field(
        description=(
            "This notebook's handle: onenote:///notebooks/{id}, with the id percent-encoded. A "
            + "handle from a group notebook starts with onenote:///groups/{group}/ instead. Pass "
            + "it to onenote_list_sections, onenote_create_section or onenote_create_section_group "
            + "to work inside the notebook. Pass it to onenote_copy_section as `to_notebook`, or "
            + "to onenote_copy_notebook as `notebook`. Never build one: a notebook id alone "
            + "reaches nothing."
        )
    )
    name: str | None = Field(
        description=(
            "The notebook's display name, as Microsoft stored it. Null when Graph did not "
            + "report one."
        )
    )
    is_default: bool | None = Field(
        description=(
            "True for the signed-in user's default notebook: the one onenote_create_page writes "
            + "into when no `section` is given. Null when Graph did not report it. This value can "
            + "come back false for the user's actual default notebook. Use onenote_list_notebooks "
            + "as the authority on which notebook is the default one."
        )
    )
    is_shared: bool | None = Field(
        description=(
            "True when this notebook is shared, so someone besides the owner can see it. Null "
            + "when Graph did not report it."
        )
    )
    user_role: str | None = Field(
        description=(
            "The signed-in user's own access to this notebook, in Microsoft's own spelling: "
            + "`Owner`, `Contributor`, `Reader`, or `None` for no access. Null when Graph did "
            + "not report it."
        )
    )
    web_url: str | None = Field(
        description=(
            "The address that opens this notebook in OneNote on the web, for the person to follow. "
            + "Null when Graph did not report one."
        )
    )
    client_url: str | None = Field(
        description=(
            "If the person has the OneNote desktop app installed, this address opens the notebook "
            + "there. Null when Graph did not report one."
        )
    )
    created_at: datetime | None = Field(
        description=(
            "When the notebook was created, as Graph reported it. Null when Graph recorded none."
        )
    )
    last_modified_at: datetime | None = Field(
        description=(
            "When the notebook last changed, as Graph reported it. Null when Graph recorded none."
        )
    )


async def find_notebook_from_url(
    client: GraphServiceClient, *, web_url: str, group: str | None = None
) -> FoundNotebook:
    assert len(web_url) >= 1, "web_url must not be empty"
    if onenote_notebook_handle(web_url) is not None:
        raise ToolError(_OWN_NOTEBOOK_HANDLE_NOT_A_WEB_ADDRESS)
    if (
        onenote_section_group_handle(web_url) is not None
        or onenote_section_handle(web_url) is not None
        or onenote_page_handle(web_url) is not None
    ):
        raise ToolError(_OWN_OTHER_HANDLE_NOT_A_WEB_ADDRESS)

    with graph_errors(TOOL_NAME, step=STEP_NOTEBOOK_FROM_URL):
        found = await _resolve(client, web_url, group)
    assert found is not None, "Graph answered getNotebookFromWebUrl with nothing"
    return _answer(found, group)


async def _resolve(
    client: GraphServiceClient, web_url: str, group_id: str | None
) -> CopyNotebookModel | None:
    builder = onenote_root(client, group_id).notebooks.get_notebook_from_web_url
    request = RequestInformation(Method.POST, builder.url_template, builder.path_parameters)
    request.headers.try_add("Accept", "application/json")
    request.set_content_from_parsable(  # pyright: ignore[reportUnknownMemberType]
        client.request_adapter,  # pyright: ignore[reportUnknownMemberType]
        "application/json",
        _post_body.GetNotebookFromWebUrlPostRequestBody(web_url=web_url),
    )
    return await client.request_adapter.send_async(  # pyright: ignore[reportUnknownMemberType]
        request, CopyNotebookModel, {"XXX": ODataError}
    )


def _answer(found: CopyNotebookModel, group_id: str | None) -> FoundNotebook:
    assert found.id is not None, (
        "Graph answered getNotebookFromWebUrl with a notebook that has no id"
    )
    return FoundNotebook(
        uri=OnenoteNotebookHandle(found.id, group_id=group_id).uri,
        name=found.name,
        is_default=found.is_default,
        is_shared=found.is_shared,
        user_role=(
            None if found.user_role is None else cast("str", cast("object", found.user_role.value))
        ),
        web_url=web_url_of(found.links),
        client_url=client_url_of(found.links),
        created_at=found.created_time,
        last_modified_at=found.last_modified_time,
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Find Notebook From URL",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def onenote_find_notebook_from_url(
        web_url: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "A OneNote web address, or Microsoft's own `onenote:` client address, exactly "
                    + "as Microsoft gave it. It can be the `web_url` of an onenote_list_notebooks "
                    + "or onenote_list_recent_notebooks row, or the `web_url` of a page or a "
                    + "section this connector already read. It can also be an address a person "
                    + "pasted. This tool refuses one of its own onenote:/// handles."
                ),
            ),
        ],
        group: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The Microsoft 365 group or team whose notebook this address opens, as its "
                    + "Graph id. A team id is a group id. Take it from teams_list_my_teams, or "
                    + "ask the user for it. Omit it for a notebook that the user owns or that "
                    + "somebody shares with them."
                ),
            ),
        ] = None,
        client: GraphServiceClient = graph,
    ) -> FoundNotebook:
        return await find_notebook_from_url(client, web_url=web_url, group=group)
