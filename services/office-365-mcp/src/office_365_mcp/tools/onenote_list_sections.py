from collections.abc import Mapping
from datetime import datetime
from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.onenote_section import OnenoteSection
from msgraph.generated.models.onenote_section_collection_response import (
    OnenoteSectionCollectionResponse,
)
from msgraph.generated.models.section_group import SectionGroup
from msgraph.generated.models.section_group_collection_response import (
    SectionGroupCollectionResponse,
)
from msgraph.generated.users.item.onenote.notebooks.item.section_groups import (
    section_groups_request_builder as _notebook_section_groups_module,
)
from msgraph.generated.users.item.onenote.notebooks.item.sections import (
    sections_request_builder as _notebook_sections_module,
)
from msgraph.generated.users.item.onenote.section_groups.item.section_groups import (
    section_groups_request_builder as _group_section_groups_module,
)
from msgraph.generated.users.item.onenote.section_groups.item.sections import (
    sections_request_builder as _group_sections_module,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import collect_pages, graph_errors, graph_step
from office_365_mcp.shared.handles import (
    OnenoteNotebookHandle,
    OnenoteSectionGroupHandle,
    OnenoteSectionHandle,
    onenote_container_handle,
)
from office_365_mcp.shared.notes import web_url_of
from office_365_mcp.shared.odata import odata_literal
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "onenote_list_sections"

STEP_SECTIONS = "sections"
STEP_SECTION_GROUPS = "section_groups"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Notes.Read",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "parent": "onenote:///notebooks/1-SYNTHETICNOTEBOOK0000"
}

MAX_SECTIONS = 100

_MIN_NAME_FRAGMENT_CHARACTERS = 1
_MAX_NAME_FRAGMENT_CHARACTERS = 200

_SECTION_FIELDS: tuple[str, ...] = (
    "id",
    "displayName",
    "isDefault",
    "lastModifiedDateTime",
    "links",
)
_SECTION_GROUP_FIELDS: tuple[str, ...] = ("id", "displayName", "lastModifiedDateTime")
_SECTION_EXPANSIONS: tuple[str, ...] = ("parentNotebook($select=id,displayName)",)

_NotebookSectionsBuilder = _notebook_sections_module.SectionsRequestBuilder
_NotebookGroupsBuilder = _notebook_section_groups_module.SectionGroupsRequestBuilder
_GroupSectionsBuilder = _group_sections_module.SectionsRequestBuilder
_GroupGroupsBuilder = _group_section_groups_module.SectionGroupsRequestBuilder

_NotebookSectionsQuery = _NotebookSectionsBuilder.SectionsRequestBuilderGetQueryParameters
_NotebookGroupsQuery = _NotebookGroupsBuilder.SectionGroupsRequestBuilderGetQueryParameters
_GroupSectionsQuery = _GroupSectionsBuilder.SectionsRequestBuilderGetQueryParameters
_GroupGroupsQuery = _GroupGroupsBuilder.SectionGroupsRequestBuilderGetQueryParameters

_DESCRIPTION = """\
Lists the sections and the section groups directly under one notebook or one section group, one \
level at a time. Both lists always come back. To walk deeper, call again with a section group's \
`uri` as `parent`. onenote_list_notebooks is the sibling for every section of every notebook in \
one call.

Notes:
- Both lists come in Microsoft's default order: ascending by name.
- Microsoft can refuse to list under a section group with error 403. Then list the notebook \
itself.
"""

_NOT_A_PARENT_HANDLE = (
    "onenote_list_sections takes a notebook handle or a section group handle in `parent`. A "
    + "notebook handle looks like onenote:///notebooks/{id} and comes from the `uri` of a "
    + "notebook in an onenote_list_notebooks result, from a onenote_find_notebook_from_url "
    + "answer, or from a onenote_create_notebook answer. A section group handle looks like "
    + "onenote:///sectiongroups/{id} and comes from the `uri` of a section group in a prior "
    + "onenote_list_sections result, or from a onenote_create_section_group answer. A section "
    + "handle (onenote:///sections/{id}), a page handle, a plain name and a web address are none "
    + "of them one of these. This same value fails again, so do not retry it."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 could not list anything under this parent. If `parent` named a notebook, the "
    + "handle is well formed, so the notebook was most likely deleted, or the signed-in user lost "
    + "access to it: call onenote_list_notebooks again and take a fresh `uri` for it, because this "
    + "same handle fails the same way again. If `parent` named a section group, it was most "
    + "likely deleted, or moved into a different notebook, which gives it a new handle: call "
    + "onenote_list_sections on that section group's own parent again and take a fresh `uri` for "
    + "it, because this same handle fails again too."
)


class SectionRow(BaseModel):
    uri: str = Field(
        description=(
            "This section's handle: onenote:///sections/{id}, with the id percent-encoded. Pass "
            + "it to onenote_list_pages, onenote_create_page, or onenote_copy_page as "
            + "`to_section`. Never build one. A section id alone reaches nothing."
        )
    )
    name: str | None = Field(
        description="The section's display name. Null when Graph did not report one."
    )
    is_default: bool | None = Field(
        description=(
            "True for the section onenote_create_page writes into, within the default "
            + "notebook, when it gets no `section`. Null when Graph did not report it."
        )
    )
    web_url: str | None = Field(
        description=(
            "The address that opens this section in OneNote on the web, for a person to follow. "
            + "This connector cannot read a page from it."
        )
    )
    last_modified_at: datetime | None = Field(
        description=(
            "When this section last changed, as Graph reported it. Null when Graph recorded none."
        )
    )


class SectionGroupRow(BaseModel):
    uri: str = Field(
        description=(
            "This section group's handle: onenote:///sectiongroups/{id}, with the id "
            + "percent-encoded. Pass it to onenote_list_sections, onenote_create_section, or "
            + "onenote_create_section_group as `parent`, or to onenote_copy_section as "
            + "`to_section_group`. Never build one. A section group id alone reaches nothing."
        )
    )
    name: str | None = Field(
        description="The section group's display name. Null when Graph did not report one."
    )
    last_modified_at: datetime | None = Field(
        description=(
            "When this section group last changed, as Graph reported it. Null when Graph "
            + "recorded none."
        )
    )


class Sections(BaseModel):
    parent_uri: str = Field(
        description="The `parent` handle this call was given, spelled back exactly as passed in."
    )
    notebook_name: str | None = Field(
        description=(
            "The display name of the notebook that holds `parent`, read off the sections "
            + "already fetched for this call at no extra Graph cost. Null when `parent` holds "
            + "no section to read it from, or when Microsoft named no parent notebook."
        )
    )
    sections: list[SectionRow] = Field(
        description=(
            "The sections that sit directly under `parent`, in Microsoft's default order. "
            + "`capped` true can leave this list incomplete. A section with no id from "
            + "Microsoft is left out. An empty list means `parent` holds no section directly. "
            + "It can still hold section groups."
        )
    )
    section_groups: list[SectionGroupRow] = Field(
        description=(
            "The section groups that sit directly under `parent`, in Microsoft's default "
            + "order. `capped` true can leave this list incomplete. A section group with no "
            + "id from Microsoft is left out. An empty list means `parent` holds no section "
            + "group directly."
        )
    )
    capped: bool = Field(
        description=(
            "True when `limit` stopped either the section listing or the section group listing "
            + f"while more rows remained. Raise `limit` while it is below {MAX_SECTIONS}, or "
            + "narrow the listing with `name_contains`. False when both listings ended on their "
            + "own."
        )
    )


async def list_sections(
    client: GraphServiceClient,
    *,
    parent: str,
    name_contains: str | None = None,
    limit: int,
) -> Sections:
    assert 1 <= limit <= MAX_SECTIONS, f"limit must be within 1..{MAX_SECTIONS}, got {limit}"
    handle = onenote_container_handle(parent)
    if handle is None:
        raise ToolError(_NOT_A_PARENT_HANDLE)
    query_filter = _name_filter(name_contains)

    with graph_errors(TOOL_NAME):
        with graph_step(STEP_SECTIONS):
            first_sections = await _first_sections(
                client, handle, limit=limit, query_filter=query_filter
            )
            assert first_sections is not None, "Graph answered a section listing with no collection"
            sections_collected = await collect_pages(
                first_sections, client, limit=limit, max_scanned=limit
            )
        with graph_step(STEP_SECTION_GROUPS):
            first_groups = await _first_section_groups(
                client, handle, limit=limit, query_filter=query_filter
            )
            assert first_groups is not None, (
                "Graph answered a section group listing with no collection"
            )
            groups_collected = await collect_pages(
                first_groups, client, limit=limit, max_scanned=limit
            )

    return Sections(
        parent_uri=handle.uri,
        notebook_name=_notebook_name(sections_collected.items),
        sections=[
            row
            for section in sections_collected.items
            if (row := _section_row(section)) is not None
        ],
        section_groups=[
            row
            for group in groups_collected.items
            if (row := _section_group_row(group)) is not None
        ],
        capped=sections_collected.capped or groups_collected.capped,
    )


def _notebook_name(sections: list[OnenoteSection]) -> str | None:
    for section in sections:
        parent_notebook = section.parent_notebook
        if parent_notebook is not None and parent_notebook.display_name is not None:
            return parent_notebook.display_name
    return None


def _name_filter(name_contains: str | None) -> str | None:
    if name_contains is None:
        return None
    literal = odata_literal(name_contains.lower())
    return f"contains(tolower(displayName),'{literal}')"


async def _first_sections(
    client: GraphServiceClient,
    handle: OnenoteNotebookHandle | OnenoteSectionGroupHandle,
    *,
    limit: int,
    query_filter: str | None,
) -> OnenoteSectionCollectionResponse | None:
    if isinstance(handle, OnenoteNotebookHandle):
        return await client.me.onenote.notebooks.by_notebook_id(handle.notebook_id).sections.get(
            request_configuration=RequestConfiguration[_NotebookSectionsQuery](
                query_parameters=_NotebookSectionsQuery(
                    select=list(_SECTION_FIELDS),
                    expand=list(_SECTION_EXPANSIONS),
                    top=limit,
                    filter=query_filter,
                )
            )
        )
    return await client.me.onenote.section_groups.by_section_group_id(
        handle.section_group_id
    ).sections.get(
        request_configuration=RequestConfiguration[_GroupSectionsQuery](
            query_parameters=_GroupSectionsQuery(
                select=list(_SECTION_FIELDS),
                expand=list(_SECTION_EXPANSIONS),
                top=limit,
                filter=query_filter,
            )
        )
    )


async def _first_section_groups(
    client: GraphServiceClient,
    handle: OnenoteNotebookHandle | OnenoteSectionGroupHandle,
    *,
    limit: int,
    query_filter: str | None,
) -> SectionGroupCollectionResponse | None:
    if isinstance(handle, OnenoteNotebookHandle):
        return await client.me.onenote.notebooks.by_notebook_id(
            handle.notebook_id
        ).section_groups.get(
            request_configuration=RequestConfiguration[_NotebookGroupsQuery](
                query_parameters=_NotebookGroupsQuery(
                    select=list(_SECTION_GROUP_FIELDS), top=limit, filter=query_filter
                )
            )
        )
    return await client.me.onenote.section_groups.by_section_group_id(
        handle.section_group_id
    ).section_groups.get(
        request_configuration=RequestConfiguration[_GroupGroupsQuery](
            query_parameters=_GroupGroupsQuery(
                select=list(_SECTION_GROUP_FIELDS), top=limit, filter=query_filter
            )
        )
    )


def _section_row(section: OnenoteSection) -> SectionRow | None:
    if section.id is None:
        return None
    return SectionRow(
        uri=OnenoteSectionHandle(section.id).uri,
        name=section.display_name,
        is_default=section.is_default,
        web_url=web_url_of(section.links),
        last_modified_at=section.last_modified_date_time,
    )


def _section_group_row(group: SectionGroup) -> SectionGroupRow | None:
    if group.id is None:
        return None
    return SectionGroupRow(
        uri=OnenoteSectionGroupHandle(group.id).uri,
        name=group.display_name,
        last_modified_at=group.last_modified_date_time,
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="List Sections",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def onenote_list_sections(
        parent: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The notebook or section group to list directly under, as a `uri`. A "
                    + "notebook's handle, onenote:///notebooks/{id}, comes from an "
                    + "onenote_list_notebooks row, a onenote_find_notebook_from_url answer, or "
                    + "a onenote_create_notebook answer. A section group's handle, "
                    + "onenote:///sectiongroups/{id}, comes from a onenote_list_sections row, "
                    + "or a onenote_create_section_group answer. A section handle, a page "
                    + "handle, a plain name and a web address are not accepted here."
                ),
            ),
        ],
        name_contains: Annotated[
            str | None,
            Field(
                min_length=_MIN_NAME_FRAGMENT_CHARACTERS,
                max_length=_MAX_NAME_FRAGMENT_CHARACTERS,
                description=(
                    "Keep only the sections and section groups whose name contains this text, "
                    + "compared without regard to case. Applies to both lists. Omit it to list "
                    + "everything directly under `parent`."
                ),
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_SECTIONS,
                description=(
                    "How many sections and how many section groups to return, at most "
                    + f"{MAX_SECTIONS} of each. Paging happens inside the call, so this is the "
                    + "whole answer, not a first page. Raise it. Do not call this tool "
                    + "again with the same arguments. `capped` says whether this limit stopped "
                    + "either listing early."
                ),
            ),
        ] = 50,
        client: GraphServiceClient = graph,
    ) -> Sections:
        return await list_sections(client, parent=parent, name_contains=name_contains, limit=limit)
