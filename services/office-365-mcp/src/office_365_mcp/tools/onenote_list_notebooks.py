from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal, cast

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
from office_365_mcp.shared.handles import (
    OnenoteNotebookHandle,
    OnenoteSectionGroupHandle,
    OnenoteSectionHandle,
)
from office_365_mcp.shared.notes import web_url_of
from office_365_mcp.shared.odata import odata_literal
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

_MIN_NAME_FRAGMENT_CHARACTERS = 1
_MAX_NAME_FRAGMENT_CHARACTERS = 200

_Role = Literal["Owner", "Contributor", "Reader"]

_DESCRIPTION = """\
List every OneNote notebook the signed-in user owns, plus every notebook someone else has \
shared with them, and every section inside each one — unless `capped` is true, in which case a \
safety cap cut one of those listings short and some notebooks or sections may be missing. This \
is the starting point for reading or writing OneNote: every other onenote_* tool takes a \
notebook's, a section group's, a section's or a page's handle. Notebook and section handles \
come from here; onenote_list_sections mints section group handles, onenote_list_pages and \
onenote_create_page mint page handles, and onenote_find_notebook_from_url and the three create \
tools mint the handle of what they resolved or created. \
`name_contains` keeps only the notebooks whose name holds this text, compared without regard to \
case. `shared` keeps only notebooks that are (true) or are not (false) shared with anyone else. \
`role` keeps only notebooks where the signed-in user holds exactly this access level: Owner, \
Contributor or Reader. All three narrow which notebooks come back; a matched notebook still \
carries every one of its own sections. Leave any of them out to list every notebook.

This covers only the notebooks reachable from the signed-in user's own OneNote: the user's own \
notebooks and the ones shared with them. It does NOT cover a notebook that lives on a \
SharePoint site or belongs to a Microsoft 365 team; no tool in this connector reaches those.

Each section's `uri` is a handle: pass it to onenote_list_pages to see the pages inside that \
section, or to onenote_create_page to write a new page into it. A section's `group_uri`, when \
it is not null, is the handle of the section group that holds it directly: pass it to \
onenote_list_sections to see what else sits in that group, to onenote_create_section or \
onenote_create_section_group to add beside it, or to onenote_copy_section as `to_section_group`. \
Each notebook's `uri` is a handle too: pass it to onenote_list_sections to see the section \
groups directly inside it as rows of their own — this tool names a section group only through \
each section's `group_uri`, never as a row by itself — or to walk one level of the notebook's \
own contents at a time; to onenote_create_section or onenote_create_section_group to add \
directly under it; to onenote_copy_section as `to_notebook`; or to onenote_copy_notebook to \
copy the whole notebook. onenote_find_notebook_from_url mints this same kind of handle from a \
web address.

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
    group_uri: str | None = Field(
        description=(
            "The handle of the section group that holds this section directly: "
            + "onenote:///sectiongroups/{id}. Pass it to onenote_list_sections to see what else "
            + "sits in that group, to onenote_create_section or onenote_create_section_group to "
            + "add beside this section, or to onenote_copy_section as `to_section_group`. Null "
            + "when this section sits directly under its notebook, with no section group in "
            + "between."
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
            + "nothing contributes an empty name to this path. This path can be cut short when "
            + "the top-level `capped` is true, because a section group the walk never reached "
            + "is left out of it."
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
    uri: str = Field(
        description=(
            "This notebook's handle: onenote:///notebooks/{id}, with the id percent-encoded. "
            + "Pass it to onenote_list_sections to see one level of this notebook's own "
            + "contents, to onenote_create_section or onenote_create_section_group to add "
            + "directly under it, to onenote_copy_section as `to_notebook`, or to "
            + "onenote_copy_notebook to copy the whole notebook. Never build one: a notebook id "
            + "alone reaches nothing."
        )
    )
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
            + "the order Microsoft returned them, unless the top-level `capped` is true, in "
            + "which case a cut happened in one of the three listings behind this answer and "
            + "this notebook's sections can be incomplete. A section Microsoft gave no id for, "
            + "or whose parent notebook this connector could not match to a notebook in this "
            + "same answer, is left out instead of being given a handle that would not resolve. "
            + "An empty list means the notebook holds no section this connector could address."
        )
    )


class Notebooks(BaseModel):
    notebooks: list[Notebook] = Field(
        description=(
            "Every notebook this call found, unless `capped` is true, in which case a cut "
            + "happened in one of the three listings behind this answer and this list can be "
            + "missing some: the signed-in user's own, and the ones shared with them. Empty "
            + "when the user has no OneNote notebooks. Microsoft sometimes returns a notebook "
            + "with no id; this connector cannot address such a notebook again, so it leaves it "
            + "out instead of giving a handle that fails."
        )
    )
    capped: bool = Field(
        description=(
            "True when a safety cap stopped one of the three listings behind this answer — "
            + "notebooks, sections, or section groups — while Microsoft still had more of it to "
            + "give, so some notebooks or sections may be missing above. When `name_contains`, "
            + "`shared` or `role` narrowed which notebooks matched, this can also be true purely "
            + "because of sections or section groups belonging to a notebook the filter "
            + "excluded: the sections and section-group listings behind this answer are not "
            + "narrowed by those same arguments. This is a safety cap, not a `limit` this tool "
            + "exposes to raise. False means every listing behind this answer finished on its "
            + "own."
        )
    )


async def list_notebooks(
    client: GraphServiceClient,
    *,
    name_contains: str | None = None,
    shared: bool | None = None,
    role: _Role | None = None,
) -> Notebooks:
    notebook_filter = _notebook_filter(name_contains, shared, role)
    with graph_errors(TOOL_NAME):
        with graph_step(STEP_NOTEBOOKS):
            first_notebooks = await client.me.onenote.notebooks.get(
                request_configuration=RequestConfiguration[_NotebooksQuery](
                    query_parameters=_NotebooksQuery(
                        select=list(_NOTEBOOK_FIELDS), filter=notebook_filter
                    )
                )
            )
            assert first_notebooks is not None, "Graph answered notebooks with no collection"
            notebooks_collected = await collect_pages(
                first_notebooks, client, limit=MAX_NOTEBOOKS, max_scanned=MAX_NOTEBOOKS
            )
        with graph_step(STEP_SECTIONS):
            first_sections = await client.me.onenote.sections.get(
                request_configuration=RequestConfiguration[_SectionsQuery](
                    query_parameters=_SectionsQuery(
                        select=list(_SECTION_FIELDS), expand=list(_HIERARCHY_EXPANSIONS)
                    )
                )
            )
            assert first_sections is not None, "Graph answered sections with no collection"
            sections_collected = await collect_pages(
                first_sections, client, limit=MAX_SECTIONS, max_scanned=MAX_SECTIONS
            )
        with graph_step(STEP_SECTION_GROUPS):
            first_groups = await client.me.onenote.section_groups.get(
                request_configuration=RequestConfiguration[_SectionGroupsQuery](
                    query_parameters=_SectionGroupsQuery(
                        select=list(_SECTION_GROUP_FIELDS), expand=list(_HIERARCHY_EXPANSIONS)
                    )
                )
            )
            assert first_groups is not None, "Graph answered section groups with no collection"
            groups_collected = await collect_pages(
                first_groups, client, limit=MAX_SECTION_GROUPS, max_scanned=MAX_SECTION_GROUPS
            )

    return _assemble(
        notebooks_collected.items,
        sections_collected.items,
        groups_collected.items,
        capped=notebooks_collected.capped or sections_collected.capped or groups_collected.capped,
    )


def _notebook_filter(
    name_contains: str | None, shared: bool | None, role: _Role | None
) -> str | None:
    clauses: list[str] = []
    if name_contains is not None:
        literal = odata_literal(name_contains.lower())
        clauses.append(f"contains(tolower(displayName),'{literal}')")
    if shared is not None:
        clauses.append(f"isShared eq {'true' if shared else 'false'}")
    if role is not None:
        clauses.append(f"userRole eq '{role}'")
    return " and ".join(clauses) if clauses else None


def _assemble(
    notebooks: list[GraphNotebook],
    sections: list[OnenoteSection],
    groups: list[SectionGroup],
    *,
    capped: bool,
) -> Notebooks:
    groups_by_id = {group.id: group for group in groups if group.id is not None}
    notebook_ids = {notebook.id for notebook in notebooks if notebook.id is not None}
    sections_by_notebook = _sections_by_notebook(sections, groups_by_id, notebook_ids)
    return Notebooks(
        notebooks=[
            row
            for notebook in notebooks
            if (row := _notebook_row(notebook, sections_by_notebook)) is not None
        ],
        capped=capped,
    )


def _notebook_row(
    notebook: GraphNotebook, sections_by_notebook: Mapping[str, list[NotebookSection]]
) -> Notebook | None:
    if notebook.id is None:
        return None
    return Notebook(
        uri=OnenoteNotebookHandle(notebook.id).uri,
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
        sections=sections_by_notebook.get(notebook.id, []),
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
            group_uri=None if group_id is None else OnenoteSectionGroupHandle(group_id).uri,
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
    async def onenote_list_notebooks(
        name_contains: Annotated[
            str | None,
            Field(
                min_length=_MIN_NAME_FRAGMENT_CHARACTERS,
                max_length=_MAX_NAME_FRAGMENT_CHARACTERS,
                description=(
                    "Keep only the notebooks whose name contains this text, compared without "
                    + "regard to case. Omit it to list every notebook regardless of name."
                ),
            ),
        ] = None,
        shared: Annotated[
            bool | None,
            Field(
                description=(
                    "Keep only notebooks that are shared with somebody besides the owner "
                    + "(true), or only ones that are not (false). Omit it to list both."
                ),
            ),
        ] = None,
        role: Annotated[
            _Role | None,
            Field(
                description=(
                    "Keep only notebooks where the signed-in user holds exactly this access "
                    + "level, as Microsoft spells it: Owner, Contributor or Reader. Omit it to "
                    + "list notebooks at every access level."
                ),
            ),
        ] = None,
        client: GraphServiceClient = graph,
    ) -> Notebooks:
        return await list_notebooks(client, name_contains=name_contains, shared=shared, role=role)
