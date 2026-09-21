from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Protocol, Self, cast

from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.external_link import ExternalLink
from msgraph.generated.models.notebook import Notebook
from msgraph.generated.models.onenote_page import OnenotePage
from msgraph.generated.users.item.onenote.notebooks.item.notebook_item_request_builder import (
    NotebookItemRequestBuilder,
)
from msgraph.generated.users.item.onenote.notebooks.notebooks_request_builder import (
    NotebooksRequestBuilder,
)
from msgraph.generated.users.item.onenote.sections.item import (
    onenote_section_item_request_builder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import collect_pages, graph_step
from office_365_mcp.shared.handles import OnenotePageHandle, OnenoteSectionHandle

PAGE_FIELDS: tuple[str, ...] = ("id", "title", "createdDateTime", "lastModifiedDateTime", "links")
PAGE_EXPANSIONS: tuple[str, ...] = ("parentSection", "parentNotebook")

NOTEBOOK_AUDIENCE_FIELDS: tuple[str, ...] = ("id", "displayName", "isShared", "userRole")
_DEFAULT_NOTEBOOK_FIELDS: tuple[str, ...] = (*NOTEBOOK_AUDIENCE_FIELDS, "isDefault")

STEP_NOTEBOOK = "notebook"
STEP_SECTION = "section"
STEP_NOTEBOOKS = "notebooks"

_MAX_NOTEBOOKS = 200

_NotebookQuery = NotebookItemRequestBuilder.NotebookItemRequestBuilderGetQueryParameters
_NotebooksQuery = NotebooksRequestBuilder.NotebooksRequestBuilderGetQueryParameters
_SectionItemBuilder = onenote_section_item_request_builder.OnenoteSectionItemRequestBuilder
_SectionQuery = _SectionItemBuilder.OnenoteSectionItemRequestBuilderGetQueryParameters


class _Links(Protocol):
    @property
    def one_note_web_url(self) -> ExternalLink | None: ...

    @property
    def one_note_client_url(self) -> ExternalLink | None: ...


def web_url_of(links: _Links | None) -> str | None:
    if links is None or links.one_note_web_url is None:
        return None
    return links.one_note_web_url.href


def client_url_of(links: _Links | None) -> str | None:
    if links is None or links.one_note_client_url is None:
        return None
    return links.one_note_client_url.href


class PageSummary(BaseModel):
    uri: str = Field(
        description=(
            "This page's handle: onenote:///pages/{id}, with the id percent-encoded. Pass it "
            + "verbatim to onenote_read_page to read the page or to onenote_append_to_page to "
            + "add to it. Never build one: a page id alone reaches nothing."
        )
    )
    title: str | None = Field(
        description=(
            "The page title as Microsoft's page index holds it. Null when the page has none. "
            + "That index lags a create or an edit, and not by minutes only: on a test tenant, a "
            + "page this connector created still came back with an empty title three days later, "
            + "while its HTML, from onenote_read_page, carried the right one from the start."
        )
    )
    created_at: datetime | None = Field(
        description=(
            "When the page was created, as Graph reported it. Null when Graph recorded none."
        )
    )
    last_modified_at: datetime | None = Field(
        description=(
            "When the page last changed, as Graph reported it. Null when Graph recorded none. A "
            + "listing of pages orders by this field, newest change first. Microsoft's page "
            + "index lags an edit, so a page written moments ago can still show the earlier "
            + "value here."
        )
    )
    web_url: str | None = Field(
        description=(
            "The address that opens this page in OneNote on the web, for a person to follow. "
            + "This connector cannot read a page from it."
        )
    )
    client_url: str | None = Field(
        description=(
            "The address that opens this page in the OneNote desktop app, if the person has it "
            + "installed."
        )
    )
    section_uri: str | None = Field(
        description=(
            "The handle of the section holding this page: onenote:///sections/{id}. Pass it to "
            + "onenote_list_pages to see this page's siblings, or to onenote_create_page to add "
            + "a page beside it. Null when Graph named no parent section for this page."
        )
    )
    section_name: str | None = Field(
        description=(
            "The display name of the section holding this page. Null when Graph gave no parent "
            + "section."
        )
    )
    notebook_name: str | None = Field(
        description=(
            "The display name of the notebook holding this page. Null when Graph gave no parent "
            + "notebook."
        )
    )

    @classmethod
    def from_page(cls, page: OnenotePage) -> Self | None:
        if page.id is None:
            return None
        section = page.parent_section
        section_id = section.id if section is not None else None
        notebook = page.parent_notebook
        return cls(
            uri=OnenotePageHandle(page.id).uri,
            title=page.title,
            created_at=page.created_date_time,
            last_modified_at=page.last_modified_date_time,
            web_url=web_url_of(page.links),
            client_url=client_url_of(page.links),
            section_uri=None if section_id is None else OnenoteSectionHandle(section_id).uri,
            section_name=section.display_name if section is not None else None,
            notebook_name=notebook.display_name if notebook is not None else None,
        )


OWNER_ROLE = "Owner"


@dataclass(frozen=True, slots=True)
class NotebookAudience:
    notebook_id: str | None
    name: str | None
    is_shared: bool | None
    user_role: str | None

    @property
    def reaches_others(self) -> bool:
        return not (self.is_shared is False and self.user_role == OWNER_ROLE)

    @property
    def reason(self) -> str:
        if self.is_shared:
            return "which is shared with other people"
        if self.user_role is not None and self.user_role != OWNER_ROLE:
            return f"which belongs to somebody else (you are {self.user_role})"
        return "whose sharing Microsoft did not report"


def audience_of(notebook: Notebook) -> NotebookAudience:
    return NotebookAudience(
        notebook_id=notebook.id,
        name=notebook.display_name,
        is_shared=notebook.is_shared,
        user_role=(
            None
            if notebook.user_role is None
            else cast("str", cast("object", notebook.user_role.value))
        ),
    )


async def notebook_audience(client: GraphServiceClient, notebook_id: str) -> NotebookAudience:
    with graph_step(STEP_NOTEBOOK):
        found = await client.me.onenote.notebooks.by_notebook_id(notebook_id).get(
            request_configuration=RequestConfiguration[_NotebookQuery](
                query_parameters=_NotebookQuery(select=list(NOTEBOOK_AUDIENCE_FIELDS))
            )
        )
    assert found is not None, "Graph answered a notebook read with no notebook"
    return audience_of(found)


async def default_notebook_audience(client: GraphServiceClient) -> NotebookAudience | None:
    with graph_step(STEP_NOTEBOOKS):
        first_page = await client.me.onenote.notebooks.get(
            request_configuration=RequestConfiguration[_NotebooksQuery](
                query_parameters=_NotebooksQuery(select=list(_DEFAULT_NOTEBOOK_FIELDS))
            )
        )
        assert first_page is not None, "Graph answered notebooks with no collection"
        collected = await collect_pages(first_page, client, limit=_MAX_NOTEBOOKS)
    return _chosen_default(collected.items, capped=collected.capped)


_UNKNOWN_AUDIENCE = NotebookAudience(notebook_id=None, name=None, is_shared=None, user_role=None)


def _chosen_default(notebooks: list[Notebook], *, capped: bool) -> NotebookAudience | None:
    if not notebooks:
        return None
    for notebook in notebooks:
        if notebook.is_default:
            return audience_of(notebook)
    if capped or len(notebooks) > 1:
        return _UNKNOWN_AUDIENCE
    return audience_of(notebooks[0])


async def section_notebook_id(client: GraphServiceClient, section_id: str) -> str | None:
    with graph_step(STEP_SECTION):
        found = await client.me.onenote.sections.by_onenote_section_id(section_id).get(
            request_configuration=RequestConfiguration[_SectionQuery](
                query_parameters=_SectionQuery(select=["id"], expand=["parentNotebook"])
            )
        )
    assert found is not None, "Graph answered a section read with no section"
    parent = found.parent_notebook
    return parent.id if parent is not None else None


def write_state_for(*parts: str) -> str:
    return sha256("\x1f".join(parts).encode()).hexdigest()
