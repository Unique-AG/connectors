from collections.abc import Mapping
from datetime import datetime
from typing import cast

import httpx
from fastmcp import FastMCP
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.notebook import Notebook as GraphNotebook
from msgraph.generated.models.onenote_section import OnenoteSection
from msgraph.generated.models.section_group import SectionGroup
from msgraph.generated.users.item.onenote.notebooks.notebooks_request_builder import (
    NotebooksRequestBuilder,
)
from msgraph.generated.users.item.onenote.section_groups.section_groups_request_builder import (
    SectionGroupsRequestBuilder,
)
from msgraph.generated.users.item.onenote.sections.sections_request_builder import (
    SectionsRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import collect_pages, graph_errors, graph_step
from office_365_mcp.shared.handles import OnenoteSectionHandle
from office_365_mcp.shared.notes import web_url_of
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "onenote_list_notebooks"

STEP_NOTEBOOKS = "notebooks"
STEP_SECTIONS = "sections"
STEP_SECTION_GROUPS = "section_groups"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Notes.Read",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {}

MAX_NOTEBOOKS = 200
MAX_SECTIONS = 2000
MAX_SECTION_GROUPS = 1000

_NOTEBOOK_FIELDS: tuple[str, ...] = (
    "id",
    "displayName",
    "isDefault",
    "isShared",
    "userRole",
    "createdDateTime",
    "lastModifiedDateTime",
    "links",
)
_SECTION_FIELDS: tuple[str, ...] = (
    "id",
    "displayName",
    "isDefault",
    "lastModifiedDateTime",
    "links",
)
_SECTION_GROUP_FIELDS: tuple[str, ...] = ("id", "displayName")
_HIERARCHY_EXPANSIONS: tuple[str, ...] = ("parentNotebook", "parentSectionGroup")

_NotebooksQuery = NotebooksRequestBuilder.NotebooksRequestBuilderGetQueryParameters
_SectionsQuery = SectionsRequestBuilder.SectionsRequestBuilderGetQueryParameters
_SectionGroupsQuery = SectionGroupsRequestBuilder.SectionGroupsRequestBuilderGetQueryParameters

_DESCRIPTION = """\
List every OneNote notebook the signed-in user owns, plus every notebook someone else has \
shared with them, and every section inside each one. This is the starting point for reading or \
writing OneNote: every other onenote_* tool takes a section's or a page's handle, and a \
section's handle comes from here. Takes no arguments.

This covers only the notebooks reachable from the signed-in user's own OneNote: the user's own \
notebooks and the ones shared with them. It does NOT cover a notebook that lives on a \
SharePoint site or belongs to a Microsoft 365 team; no tool in this connector reaches those.

Each section's `uri` is a handle: pass it to onenote_list_pages to see the pages inside that \
section, or to onenote_create_page to write a new page into it. A notebook and a section group \
carry no handle of their own, because no tool here takes one — only a section or a page is ever \
addressed directly.

`is_default` on a notebook names the notebook onenote_create_page writes into when it is called \
with no section at all; `is_default` on a section, inside that same notebook, names the section \
that write lands in. A section's `group_path` says where the section sits inside its notebook \
when one or more section groups sit between them: names joined outermost first. It is null for \
a section that sits directly under its notebook.\
"""


class NotebookSection(BaseModel):
    uri: str = Field(
        description=(
            "This section's handle: onenote:///sections/{id}, with the id percent-encoded. Pass "
            + "it to onenote_list_pages to see the pages inside it, or to onenote_create_page to "
            + "write a new page into it. Never build one: a section id alone reaches nothing."
        )
    )
    name: str | None = Field(
        description="The section's display name. Null when Microsoft named none."
    )
    group_path: str | None = Field(
        description=(
            "Where this section sits inside its notebook, when one or more section groups sit "
            + 'between the notebook and the section: their names joined with " / ", outermost '
            + 'first, for example "Projects / 2026". Null when the section sits directly under '
            + "its notebook, with no section group in between. A section group Microsoft named "
            + "nothing contributes an empty name to this path."
        )
    )
    is_default: bool | None = Field(
        description=(
            "True for the section onenote_create_page writes a page into when it is called with "
            + "no section at all and this section's notebook is also the default one. Null when "
            + "Microsoft did not say."
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


class Notebook(BaseModel):
    name: str | None = Field(
        description="The notebook's display name. Null when Microsoft named none."
    )
    is_default: bool | None = Field(
        description=(
            "True for the signed-in user's default notebook: the one onenote_create_page writes "
            + "into when it is called with no section at all. Null when Microsoft did not say."
        )
    )
    is_shared: bool | None = Field(
        description=(
            "True when this notebook is shared, so someone besides the owner can see it. Null "
            + "when Microsoft did not say."
        )
    )
    user_role: str | None = Field(
        description=(
            "The signed-in user's own access to this notebook, exactly as Microsoft spells it: "
            + '"Owner", "Contributor", "Reader", or "None" for no access. Null when Microsoft did '
            + "not say."
        )
    )
    web_url: str | None = Field(
        description=(
            "The address that opens this notebook in OneNote on the web, for a person to follow."
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
    sections: list[NotebookSection] = Field(
        description=(
            "Every section inside this notebook, directly or nested inside a section group, in "
            + "the order Microsoft returned them. A section Microsoft gave no id for, or whose "
            + "parent notebook this connector could not match to a notebook in this same answer, "
            + "is left out instead of being given a handle that would not resolve. An empty list "
            + "means the notebook holds no section this connector could address."
        )
    )


class Notebooks(BaseModel):
    notebooks: list[Notebook] = Field(
        description=(
            "Every notebook this call found: the signed-in user's own, and the ones shared with "
            + "them. Empty when the user has no OneNote notebooks."
        )
    )


async def list_notebooks(client: GraphServiceClient) -> Notebooks:
    with graph_errors(TOOL_NAME):
        with graph_step(STEP_NOTEBOOKS):
            first_notebooks = await client.me.onenote.notebooks.get(
                request_configuration=RequestConfiguration[_NotebooksQuery](
                    query_parameters=_NotebooksQuery(select=list(_NOTEBOOK_FIELDS))
                )
            )
            assert first_notebooks is not None, "Graph answered notebooks with no collection"
            notebooks_collected = await collect_pages(first_notebooks, client, limit=MAX_NOTEBOOKS)
        with graph_step(STEP_SECTIONS):
            first_sections = await client.me.onenote.sections.get(
                request_configuration=RequestConfiguration[_SectionsQuery](
                    query_parameters=_SectionsQuery(
                        select=list(_SECTION_FIELDS), expand=list(_HIERARCHY_EXPANSIONS)
                    )
                )
            )
            assert first_sections is not None, "Graph answered sections with no collection"
            sections_collected = await collect_pages(first_sections, client, limit=MAX_SECTIONS)
        with graph_step(STEP_SECTION_GROUPS):
            first_groups = await client.me.onenote.section_groups.get(
                request_configuration=RequestConfiguration[_SectionGroupsQuery](
                    query_parameters=_SectionGroupsQuery(
                        select=list(_SECTION_GROUP_FIELDS), expand=list(_HIERARCHY_EXPANSIONS)
                    )
                )
            )
            assert first_groups is not None, "Graph answered section groups with no collection"
            groups_collected = await collect_pages(first_groups, client, limit=MAX_SECTION_GROUPS)

    return _assemble(notebooks_collected.items, sections_collected.items, groups_collected.items)


def _assemble(
    notebooks: list[GraphNotebook], sections: list[OnenoteSection], groups: list[SectionGroup]
) -> Notebooks:
    groups_by_id = {group.id: group for group in groups if group.id is not None}
    notebook_ids = {notebook.id for notebook in notebooks if notebook.id is not None}
    sections_by_notebook = _sections_by_notebook(sections, groups_by_id, notebook_ids)
    return Notebooks(
        notebooks=[_notebook_row(notebook, sections_by_notebook) for notebook in notebooks]
    )


def _notebook_row(
    notebook: GraphNotebook, sections_by_notebook: Mapping[str, list[NotebookSection]]
) -> Notebook:
    rows = [] if notebook.id is None else sections_by_notebook.get(notebook.id, [])
    return Notebook(
        name=notebook.display_name,
        is_default=notebook.is_default,
        is_shared=notebook.is_shared,
        user_role=(
            None
            if notebook.user_role is None
            else cast("str", cast("object", notebook.user_role.value))
        ),
        web_url=web_url_of(notebook.links),
        created_at=notebook.created_date_time,
        last_modified_at=notebook.last_modified_date_time,
        sections=rows,
    )


def _sections_by_notebook(
    sections: list[OnenoteSection],
    groups_by_id: Mapping[str, SectionGroup],
    notebook_ids: set[str],
) -> dict[str, list[NotebookSection]]:
    by_notebook: dict[str, list[NotebookSection]] = {}
    for section in sections:
        if section.id is None:
            continue
        notebook = section.parent_notebook
        notebook_id = notebook.id if notebook is not None else None
        if notebook_id is None or notebook_id not in notebook_ids:
            continue
        parent_group = section.parent_section_group
        group_id = parent_group.id if parent_group is not None else None
        row = NotebookSection(
            uri=OnenoteSectionHandle(section.id).uri,
            name=section.display_name,
            group_path=_group_path(group_id, groups_by_id),
            is_default=section.is_default,
            web_url=web_url_of(section.links),
            last_modified_at=section.last_modified_date_time,
        )
        by_notebook.setdefault(notebook_id, []).append(row)
    return by_notebook


def _group_path(group_id: str | None, groups_by_id: Mapping[str, SectionGroup]) -> str | None:
    names: list[str] = []
    visited: set[str] = set()
    current = group_id
    while current is not None and current not in visited:
        visited.add(current)
        group = groups_by_id.get(current)
        if group is None:
            break
        names.append(group.display_name or "")
        parent = group.parent_section_group
        current = parent.id if parent is not None else None
    return " / ".join(reversed(names)) if names else None


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="List Notebooks",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def onenote_list_notebooks(client: GraphServiceClient = graph) -> Notebooks:
        return await list_notebooks(client)
