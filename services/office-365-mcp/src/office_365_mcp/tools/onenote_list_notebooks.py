from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal, cast

import httpx
from fastmcp import FastMCP
from msgraph.generated.models.notebook import Notebook as GraphNotebook
from msgraph.generated.models.notebook_collection_response import NotebookCollectionResponse
from msgraph.generated.models.onenote_section import OnenoteSection
from msgraph.generated.models.onenote_section_collection_response import (
    OnenoteSectionCollectionResponse,
)
from msgraph.generated.models.section_group import SectionGroup
from msgraph.generated.models.section_group_collection_response import (
    SectionGroupCollectionResponse,
)
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

from office_365_mcp.graph_client import MAX_SCANNED_ITEMS, collect_pages, graph_errors, graph_step
from office_365_mcp.shared.handles import (
    OnenoteNotebookHandle,
    OnenoteSectionGroupHandle,
    OnenoteSectionHandle,
)
from office_365_mcp.shared.notes import (
    CONTAINER_ORDER_CLAUSES,
    ContainerOrderBy,
    created_by_contains,
    creator_name_of,
    get_with_query,
    onenote_root,
    web_url_of,
)
from office_365_mcp.shared.odata import odata_literal
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "onenote_list_notebooks"

STEP_NOTEBOOKS = "notebooks"
STEP_SECTIONS = "sections"
STEP_SECTION_GROUPS = "section_groups"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Notes.Read",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {}

GRAPH_NOT_FOUND = (
    "Microsoft 365 will not list these notebooks. If this call named a `group`, the id most "
    + "likely names no group that the signed-in user can reach. Take the id from "
    + "teams_list_my_teams, or ask the user for it. This same id fails again, so do not retry "
    + "it. If this call named no `group`, Microsoft most likely found no OneNote for this "
    + "account, and no other argument fixes that."
)

_NOTEBOOK_FIELDS: tuple[str, ...] = (
    "id",
    "displayName",
    "isDefault",
    "isShared",
    "userRole",
    "createdBy",
    "createdDateTime",
    "lastModifiedDateTime",
    "links",
)
_SECTION_FIELDS: tuple[str, ...] = (
    "id",
    "displayName",
    "isDefault",
    "createdBy",
    "lastModifiedDateTime",
    "links",
)
_SECTION_GROUP_FIELDS: tuple[str, ...] = ("id", "displayName")
_HIERARCHY_EXPANSIONS: tuple[str, ...] = ("parentNotebook", "parentSectionGroup")

_NotebooksQuery = NotebooksRequestBuilder.NotebooksRequestBuilderGetQueryParameters
_SectionsQuery = SectionsRequestBuilder.SectionsRequestBuilderGetQueryParameters
_SectionGroupsQuery = SectionGroupsRequestBuilder.SectionGroupsRequestBuilderGetQueryParameters

_MIN_NAME_FRAGMENT_CHARACTERS = 1

_Role = Literal["Owner", "Contributor", "Reader"]

_DESCRIPTION = """\
Lists every notebook the signed-in user owns or that somebody else shares with them, with every \
section of each. This is the starting point for OneNote: notebook and section handles come from \
here. A section group appears only through a section's `group_uri`. onenote_list_sections lists \
section groups as rows. Pass `group` to list the notebooks of one Microsoft 365 group or team \
instead. This tool does not reach a notebook on a SharePoint site.

Notes:
- `capped` true means a safety cap cut the listing short.
"""


class NotebookSection(BaseModel):
    uri: str = Field(
        description=(
            "This section's handle: onenote:///sections/{id}, with the id percent-encoded. A "
            + "handle from a group notebook starts with onenote:///groups/{group}/ instead. Pass "
            + "it as `section` to onenote_list_pages or onenote_create_page, or as `to_section` "
            + "to onenote_copy_page. Never build one. A section id alone reaches nothing."
        )
    )
    group_uri: str | None = Field(
        description=(
            "The handle of the section group that holds this section directly: "
            + "onenote:///sectiongroups/{id}. A handle from a group notebook starts with "
            + "onenote:///groups/{group}/ instead. Pass it to onenote_list_sections, "
            + "onenote_create_section, or onenote_create_section_group as `parent`, or to "
            + "onenote_copy_section as `to_section_group`. Null when this section sits directly "
            + "under its notebook."
        )
    )
    name: str | None = Field(
        description="The section's display name. Null when Graph did not report one."
    )
    group_path: str | None = Field(
        description=(
            "The names of the section groups above this section, outermost first, joined with "
            + '" / ", for example "Projects / 2026". Null when the section sits directly under '
            + "its notebook. `capped` true can leave this path incomplete."
        )
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
    created_by: str | None = Field(
        description=(
            "The display name of the person who created this section, as Graph reported it. "
            + "Null when Graph named no person."
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
            "This notebook's handle: onenote:///notebooks/{id}, with the id percent-encoded. A "
            + "handle from a group notebook starts with onenote:///groups/{group}/ instead. "
            + "Pass it as `parent` to onenote_list_sections, onenote_create_section or "
            + "onenote_create_section_group, as `to_notebook` to onenote_copy_section, or as "
            + "`notebook` to onenote_copy_notebook. Never build one. A notebook id alone reaches "
            + "nothing."
        )
    )
    name: str | None = Field(
        description="The notebook's display name. Null when Graph did not report one."
    )
    is_default: bool | None = Field(
        description=(
            "True for the notebook onenote_create_page writes into when it gets no `section`. "
            + "Null when Graph did not report it."
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
            "The signed-in user's own access to this notebook, exactly as Microsoft spells it: "
            + '"Owner", "Contributor", "Reader", or "None" for no access. Null when Graph did '
            + "not report it."
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
    created_by: str | None = Field(
        description=(
            "The display name of the person who created this notebook, as Graph reported it. "
            + "Null when Graph named no person."
        )
    )
    last_modified_at: datetime | None = Field(
        description=(
            "When the notebook last changed, as Graph reported it. Null when Graph recorded none."
        )
    )
    sections: list[NotebookSection] = Field(
        description=(
            "Every section inside this notebook, directly or in a section group, in the order "
            + "Microsoft returned them. `capped` true can leave this list incomplete. A section "
            + "with no id, or an unmatched parent notebook, is left out. Empty means the "
            + "notebook holds no section this connector can address."
        )
    )


class Notebooks(BaseModel):
    notebooks: list[Notebook] = Field(
        description=(
            "Every notebook this call found. With no `group`, these are the signed-in user's "
            + "own notebooks and the ones shared with them. With `group`, these are the "
            + "notebooks of that group. `capped` true can leave this list incomplete. Empty when "
            + "no notebook matches. A notebook with no id from Microsoft is left out. It never "
            + "gets a handle that fails."
        )
    )
    capped: bool = Field(
        description=(
            "True when a safety cap stopped the notebook, section, or section-group listing "
            + "behind this answer, not a `limit` this tool exposes to raise. `name_contains`, "
            + "`created_by`, `shared`, and `role` narrow only the notebook listing, so an "
            + "excluded notebook's own listing can still trigger this. False means every listing "
            + "finished on its own."
        )
    )


async def list_notebooks(
    client: GraphServiceClient,
    *,
    group: str | None = None,
    name_contains: str | None = None,
    created_by: str | None = None,
    shared: bool | None = None,
    role: _Role | None = None,
    order_by: ContainerOrderBy | None = None,
) -> Notebooks:
    notebook_filter = _notebook_filter(name_contains, shared, role)
    orderby = None if order_by is None else [CONTAINER_ORDER_CLAUSES[order_by]]
    root = onenote_root(client, group)
    with graph_errors(TOOL_NAME):
        with graph_step(STEP_NOTEBOOKS):
            first_notebooks = await get_with_query(
                client,
                root.notebooks,
                _NotebooksQuery(
                    select=list(_NOTEBOOK_FIELDS), filter=notebook_filter, orderby=orderby
                ),
                NotebookCollectionResponse,
            )
            assert first_notebooks is not None, "Graph answered notebooks with no collection"
            notebooks_collected = await collect_pages(
                first_notebooks,
                client,
                limit=MAX_SCANNED_ITEMS,
                matches=None if created_by is None else created_by_contains(created_by),
            )
        with graph_step(STEP_SECTIONS):
            first_sections = await get_with_query(
                client,
                root.sections,
                _SectionsQuery(
                    select=list(_SECTION_FIELDS),
                    expand=list(_HIERARCHY_EXPANSIONS),
                    orderby=orderby,
                ),
                OnenoteSectionCollectionResponse,
            )
            assert first_sections is not None, "Graph answered sections with no collection"
            sections_collected = await collect_pages(
                first_sections, client, limit=MAX_SCANNED_ITEMS
            )
        with graph_step(STEP_SECTION_GROUPS):
            first_groups = await get_with_query(
                client,
                root.section_groups,
                _SectionGroupsQuery(
                    select=list(_SECTION_GROUP_FIELDS), expand=list(_HIERARCHY_EXPANSIONS)
                ),
                SectionGroupCollectionResponse,
            )
            assert first_groups is not None, "Graph answered section groups with no collection"
            groups_collected = await collect_pages(first_groups, client, limit=MAX_SCANNED_ITEMS)

    return _assemble(
        notebooks_collected.items,
        sections_collected.items,
        groups_collected.items,
        group_id=group,
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
    group_id: str | None,
    capped: bool,
) -> Notebooks:
    groups_by_id = {group.id: group for group in groups if group.id is not None}
    notebook_ids = {notebook.id for notebook in notebooks if notebook.id is not None}
    sections_by_notebook = _sections_by_notebook(sections, groups_by_id, notebook_ids, group_id)
    return Notebooks(
        notebooks=[
            row
            for notebook in notebooks
            if (row := _notebook_row(notebook, sections_by_notebook, group_id)) is not None
        ],
        capped=capped,
    )


def _notebook_row(
    notebook: GraphNotebook,
    sections_by_notebook: Mapping[str, list[NotebookSection]],
    group_id: str | None,
) -> Notebook | None:
    if notebook.id is None:
        return None
    return Notebook(
        uri=OnenoteNotebookHandle(notebook.id, group_id=group_id).uri,
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
        created_by=creator_name_of(notebook.created_by),
        last_modified_at=notebook.last_modified_date_time,
        sections=sections_by_notebook.get(notebook.id, []),
    )


def _sections_by_notebook(
    sections: list[OnenoteSection],
    groups_by_id: Mapping[str, SectionGroup],
    notebook_ids: set[str],
    group_id: str | None,
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
        section_group_id = parent_group.id if parent_group is not None else None
        row = NotebookSection(
            uri=OnenoteSectionHandle(section.id, group_id=group_id).uri,
            group_uri=(
                None
                if section_group_id is None
                else OnenoteSectionGroupHandle(section_group_id, group_id=group_id).uri
            ),
            name=section.display_name,
            group_path=_group_path(section_group_id, groups_by_id),
            is_default=section.is_default,
            web_url=web_url_of(section.links),
            created_by=creator_name_of(section.created_by),
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
        group: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The Microsoft 365 group or team whose notebooks this call lists, as its "
                    + "Graph id. A team id is a group id. Take it from teams_list_my_teams, or "
                    + "ask the user for it. Omit it to list every notebook the user owns or that "
                    + "somebody shares with them."
                ),
            ),
        ] = None,
        name_contains: Annotated[
            str | None,
            Field(
                min_length=_MIN_NAME_FRAGMENT_CHARACTERS,
                description=(
                    "Keep only the notebooks whose name contains this text, compared without "
                    + "regard to case. A matched notebook still carries every one of its "
                    + "sections. Omit it to list every notebook."
                ),
            ),
        ] = None,
        created_by: Annotated[
            str | None,
            Field(
                min_length=_MIN_NAME_FRAGMENT_CHARACTERS,
                description=(
                    "Keep only the notebooks whose `created_by` value contains this text, "
                    + "compared without regard to case. A notebook with a null `created_by` is "
                    + "left out. A kept notebook still carries every one of its sections. Omit "
                    + "it to list every notebook."
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
        order_by: Annotated[
            ContainerOrderBy | None,
            Field(
                description=(
                    "Sort the notebooks, and the sections inside each notebook, instead of the "
                    + "default order. `name_asc`/`name_desc` sorts by display name. "
                    + "`created_desc`/`created_asc` sorts by when an item was created. "
                    + "`last_modified_desc`/`last_modified_asc` sorts by when it last changed. "
                    + "Omit it to keep the default order."
                ),
            ),
        ] = None,
        client: GraphServiceClient = graph,
    ) -> Notebooks:
        return await list_notebooks(
            client,
            group=group,
            name_contains=name_contains,
            created_by=created_by,
            shared=shared,
            role=role,
            order_by=order_by,
        )
