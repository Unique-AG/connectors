import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Literal, Protocol, Self, cast
from urllib.parse import unquote, urlsplit

from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_serialization_json.json_parse_node_factory import JsonParseNodeFactory
from msgraph.generated.models.external_link import ExternalLink
from msgraph.generated.models.notebook import Notebook
from msgraph.generated.models.onenote_operation import OnenoteOperation
from msgraph.generated.models.onenote_page import OnenotePage
from msgraph.generated.models.operation_status import OperationStatus
from msgraph.generated.users.item.onenote.notebooks.item.notebook_item_request_builder import (
    NotebookItemRequestBuilder,
)
from msgraph.generated.users.item.onenote.notebooks.notebooks_request_builder import (
    NotebooksRequestBuilder,
)
from msgraph.generated.users.item.onenote.pages.item.onenote_page_item_request_builder import (
    OnenotePageItemRequestBuilder,
)
from msgraph.generated.users.item.onenote.section_groups.item import (
    section_group_item_request_builder,
)
from msgraph.generated.users.item.onenote.sections.item import (
    onenote_section_item_request_builder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import FetchedResponse, collect_pages, graph_step
from office_365_mcp.shared.handles import (
    OnenoteNotebookHandle,
    OnenoteOperationHandle,
    OnenotePageHandle,
    OnenoteSectionGroupHandle,
    OnenoteSectionHandle,
)

PAGE_FIELDS: tuple[str, ...] = ("id", "title", "createdDateTime", "lastModifiedDateTime", "links")
PAGE_EXPANSIONS: tuple[str, ...] = ("parentSection", "parentNotebook")

NOTEBOOK_AUDIENCE_FIELDS: tuple[str, ...] = ("id", "displayName", "isShared", "userRole")
_DEFAULT_NOTEBOOK_FIELDS: tuple[str, ...] = (*NOTEBOOK_AUDIENCE_FIELDS, "isDefault")

STEP_NOTEBOOK = "notebook"
STEP_SECTION = "section"
STEP_SECTION_GROUP = "section_group"
STEP_NOTEBOOKS = "notebooks"
STEP_PAGE = "page"

_MAX_NOTEBOOKS = 200

_NotebookQuery = NotebookItemRequestBuilder.NotebookItemRequestBuilderGetQueryParameters
_NotebooksQuery = NotebooksRequestBuilder.NotebooksRequestBuilderGetQueryParameters
_SectionItemBuilder = onenote_section_item_request_builder.OnenoteSectionItemRequestBuilder
_SectionQuery = _SectionItemBuilder.OnenoteSectionItemRequestBuilderGetQueryParameters
_SectionGroupItemBuilder = section_group_item_request_builder.SectionGroupItemRequestBuilder
_SectionGroupQuery = _SectionGroupItemBuilder.SectionGroupItemRequestBuilderGetQueryParameters
_PageQuery = OnenotePageItemRequestBuilder.OnenotePageItemRequestBuilderGetQueryParameters


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
    level: int | None = Field(
        description=(
            "How deeply this page is indented under another page in its section: 0 for a "
            + "top-level page, 1 for a page indented one level under it, and so on. Always null "
            + "unless onenote_list_pages was asked for it with include_level_and_order=true."
        )
    )
    order: int | None = Field(
        description=(
            "Where this page sits among the other pages of its section, in Microsoft's own "
            + "ordering. Always null unless onenote_list_pages was asked for it with "
            + "include_level_and_order=true."
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
            level=page.level,
            order=page.order,
        )


async def page_summary(client: GraphServiceClient, page_id: str) -> PageSummary:
    with graph_step(STEP_PAGE):
        found = await client.me.onenote.pages.by_onenote_page_id(page_id).get(
            request_configuration=RequestConfiguration[_PageQuery](
                query_parameters=_PageQuery(select=list(PAGE_FIELDS), expand=list(PAGE_EXPANSIONS))
            )
        )
    assert found is not None, "Graph answered a page re-read with no page"
    summary = PageSummary.from_page(found)
    assert summary is not None, "Graph re-read a page it gave no id, which cannot be addressed"
    return summary


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


UNKNOWN_AUDIENCE = NotebookAudience(notebook_id=None, name=None, is_shared=None, user_role=None)


def _chosen_default(notebooks: list[Notebook], *, capped: bool) -> NotebookAudience | None:
    if not notebooks:
        return None
    for notebook in notebooks:
        if notebook.is_default:
            return audience_of(notebook)
    if capped or len(notebooks) > 1:
        return UNKNOWN_AUDIENCE
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


async def section_group_notebook_id(
    client: GraphServiceClient, section_group_id: str
) -> str | None:
    with graph_step(STEP_SECTION_GROUP):
        found = await client.me.onenote.section_groups.by_section_group_id(section_group_id).get(
            request_configuration=RequestConfiguration[_SectionGroupQuery](
                query_parameters=_SectionGroupQuery(select=["id"], expand=["parentNotebook"])
            )
        )
    assert found is not None, "Graph answered a section group read with no section group"
    parent = found.parent_notebook
    return parent.id if parent is not None else None


_CONTAINER_FIELDS: tuple[str, ...] = ("id", "displayName")


@dataclass(frozen=True, slots=True)
class ContainerAudience:
    name: str | None
    notebook: NotebookAudience


async def _audience_of_notebook_id(
    client: GraphServiceClient, notebook_id: str | None
) -> NotebookAudience:
    if notebook_id is None:
        return UNKNOWN_AUDIENCE
    return await notebook_audience(client, notebook_id)


async def section_container(client: GraphServiceClient, section_id: str) -> ContainerAudience:
    with graph_step(STEP_SECTION):
        found = await client.me.onenote.sections.by_onenote_section_id(section_id).get(
            request_configuration=RequestConfiguration[_SectionQuery](
                query_parameters=_SectionQuery(
                    select=list(_CONTAINER_FIELDS), expand=["parentNotebook"]
                )
            )
        )
    assert found is not None, "Graph answered a section read with no section"
    parent = found.parent_notebook
    notebook_id = parent.id if parent is not None else None
    return ContainerAudience(
        name=found.display_name, notebook=await _audience_of_notebook_id(client, notebook_id)
    )


async def section_group_container(
    client: GraphServiceClient, section_group_id: str
) -> ContainerAudience:
    with graph_step(STEP_SECTION_GROUP):
        found = await client.me.onenote.section_groups.by_section_group_id(section_group_id).get(
            request_configuration=RequestConfiguration[_SectionGroupQuery](
                query_parameters=_SectionGroupQuery(
                    select=list(_CONTAINER_FIELDS), expand=["parentNotebook"]
                )
            )
        )
    assert found is not None, "Graph answered a section group read with no section group"
    parent = found.parent_notebook
    notebook_id = parent.id if parent is not None else None
    return ContainerAudience(
        name=found.display_name, notebook=await _audience_of_notebook_id(client, notebook_id)
    )


async def section_audience(client: GraphServiceClient, section_id: str) -> NotebookAudience:
    return (await section_container(client, section_id)).notebook


async def section_group_audience(
    client: GraphServiceClient, section_group_id: str
) -> NotebookAudience:
    return (await section_group_container(client, section_group_id)).notebook


async def container_audience(
    client: GraphServiceClient, handle: OnenoteNotebookHandle | OnenoteSectionGroupHandle
) -> ContainerAudience:
    if isinstance(handle, OnenoteNotebookHandle):
        notebook = await notebook_audience(client, handle.notebook_id)
        return ContainerAudience(name=notebook.name, notebook=notebook)
    return await section_group_container(client, handle.section_group_id)


_PAGE_FOR_A_QUESTION_FIELDS: tuple[str, ...] = ("id", "title")
_PAGE_FOR_A_QUESTION_EXPANSIONS: tuple[str, ...] = ("parentNotebook", "parentSection")


@dataclass(frozen=True, slots=True)
class PageForAQuestion:
    page: OnenotePage
    audience: NotebookAudience


async def page_for_a_question(client: GraphServiceClient, page_id: str) -> PageForAQuestion:
    with graph_step(STEP_PAGE):
        found = await client.me.onenote.pages.by_onenote_page_id(page_id).get(
            request_configuration=RequestConfiguration[_PageQuery](
                query_parameters=_PageQuery(
                    select=list(_PAGE_FOR_A_QUESTION_FIELDS),
                    expand=list(_PAGE_FOR_A_QUESTION_EXPANSIONS),
                )
            )
        )
    assert found is not None, "Graph answered a page read with no page"
    parent = found.parent_notebook
    notebook_id = parent.id if parent is not None else None
    return PageForAQuestion(
        page=found, audience=await _audience_of_notebook_id(client, notebook_id)
    )


_RESOURCE_LOCATION = re.compile(r"/onenote/(pages|sections|notebooks)/([^/]+)/?\Z")

_RESOURCE_KIND_OF: Mapping[str, Literal["page", "section", "notebook"]] = {
    "pages": "page",
    "sections": "section",
    "notebooks": "notebook",
}


def resource_handle_of(
    location: str | None, resource_id: str | None
) -> tuple[str, Literal["page", "section", "notebook"]] | None:
    if location is None:
        return None
    match = _RESOURCE_LOCATION.search(urlsplit(location).path)
    if match is None:
        return None
    family, encoded_id = match.groups()
    resolved_id = resource_id if resource_id is not None else unquote(encoded_id)
    kind = _RESOURCE_KIND_OF[family]
    if family == "pages":
        return OnenotePageHandle(resolved_id).uri, kind
    if family == "sections":
        return OnenoteSectionHandle(resolved_id).uri, kind
    return OnenoteNotebookHandle(resolved_id).uri, kind


_RESOURCE_ID_IN_URL = re.compile(r"/onenote/resources/([^/?#]+)(?:/\$value|/content)?/?(?:[?#]|\Z)")


def resource_id_in(url: str) -> str | None:
    match = _RESOURCE_ID_IN_URL.search(url)
    return None if match is None else unquote(match.group(1))


_OPERATION_ID_IN_URL = re.compile(r"/onenote/operations/([^/?#]+)/?(?:[?#]|\Z)")


def operation_id_in(location: str | None) -> str | None:
    if location is None:
        return None
    match = _OPERATION_ID_IN_URL.search(location)
    return None if match is None else unquote(match.group(1))


OperationState = Literal["NotStarted", "Running", "Completed", "Failed"]

_STATUS_TEXT: Mapping[OperationStatus, OperationState] = {
    OperationStatus.NotStarted: "NotStarted",
    OperationStatus.Running: "Running",
    OperationStatus.Completed: "Completed",
    OperationStatus.Failed: "Failed",
}


class OperationSummary(BaseModel):
    uri: str = Field(
        description=(
            "This operation's handle: onenote:///operations/{id}, with the id percent-encoded. "
            + "Pass it to onenote_get_operation to poll it. Never build one: an operation id "
            + "alone reaches nothing."
        )
    )
    status: OperationState | None = Field(
        description=(
            "Microsoft's own status word for this operation: NotStarted, Running, Completed or "
            + "Failed. Null right after a copy is accepted, before Microsoft has reported any "
            + "status; poll onenote_get_operation with `uri` to fill it in, and keep polling "
            + "until it reads Completed or Failed."
        )
    )
    percent_complete: str | None = Field(
        description=(
            "How far along Graph says the operation is, as the digits of a percentage. "
            + "Microsoft reports this as text, not a number. Null while Graph has nothing to "
            + "report."
        )
    )
    created_at: datetime | None = Field(
        description="When the operation started, as Graph reported it. Null when Graph gave none."
    )
    last_action_at: datetime | None = Field(
        description=("When Graph last acted on this operation. Null when Graph gave none.")
    )
    result_uri: str | None = Field(
        description=(
            "The handle of the page, section or notebook this operation produced, once `status` "
            + "reads Completed. Null until then, and null when Graph named no result."
        )
    )
    result_kind: Literal["page", "section", "notebook"] | None = Field(
        description=(
            "What `result_uri` addresses: page, section or notebook. Null exactly when "
            + "`result_uri` is null."
        )
    )
    error_code: str | None = Field(
        description=(
            "Microsoft's error code for this operation, present only when `status` reads "
            + "Failed. Null otherwise."
        )
    )
    error_message: str | None = Field(
        description=(
            "Microsoft's error message for this operation, present only when `status` reads "
            + "Failed. Null otherwise."
        )
    )

    @classmethod
    def from_operation(cls, op: OnenoteOperation) -> Self:
        assert op.id is not None, "Graph answered with an operation that has no id"
        result = resource_handle_of(op.resource_location, op.resource_id)
        result_uri, result_kind = result if result is not None else (None, None)
        error = op.error
        return cls(
            uri=OnenoteOperationHandle(op.id).uri,
            status=(None if op.status is None else _STATUS_TEXT[op.status]),
            percent_complete=op.percent_complete,
            created_at=op.created_date_time,
            last_action_at=op.last_action_date_time,
            result_uri=result_uri,
            result_kind=result_kind,
            error_code=error.code if error is not None else None,
            error_message=error.message if error is not None else None,
        )

    @classmethod
    def accepted(cls, operation_id: str) -> Self:
        return cls(
            uri=OnenoteOperationHandle(operation_id).uri,
            status=None,
            percent_complete=None,
            created_at=None,
            last_action_at=None,
            result_uri=None,
            result_kind=None,
            error_code=None,
            error_message=None,
        )


def accepted_operation(fetched: FetchedResponse) -> OperationSummary | None:
    if fetched.content:
        node = JsonParseNodeFactory().get_root_parse_node("application/json", fetched.content)
        operation = node.get_object_value(OnenoteOperation)
        if operation.id is not None:
            return OperationSummary.from_operation(operation)
    operation_id = operation_id_in(fetched.headers.get("operation-location"))
    return None if operation_id is None else OperationSummary.accepted(operation_id)


def write_state_for(*parts: str) -> str:
    return sha256("\x1f".join(parts).encode()).hexdigest()
