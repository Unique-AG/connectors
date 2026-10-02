import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256
from typing import Literal, Protocol, Self, assert_never, cast
from urllib.parse import unquote, urlsplit

from kiota_abstractions.base_request_builder import BaseRequestBuilder
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.method import Method
from kiota_abstractions.request_information import RequestInformation
from kiota_abstractions.serialization.parsable import Parsable
from kiota_abstractions.serialization.parsable_factory import ParsableFactory
from kiota_serialization_json.json_parse_node_factory import JsonParseNodeFactory
from msgraph.generated.groups.item.onenote import onenote_request_builder as group_onenote
from msgraph.generated.models.external_link import ExternalLink
from msgraph.generated.models.identity_set import IdentitySet
from msgraph.generated.models.notebook import Notebook
from msgraph.generated.models.o_data_errors.o_data_error import ODataError
from msgraph.generated.models.onenote_operation import OnenoteOperation
from msgraph.generated.models.onenote_page import OnenotePage
from msgraph.generated.models.onenote_patch_content_command import OnenotePatchContentCommand
from msgraph.generated.models.onenote_section import OnenoteSection
from msgraph.generated.models.operation_status import OperationStatus
from msgraph.generated.models.section_group import SectionGroup
from msgraph.generated.sites.item.onenote import onenote_request_builder as site_onenote
from msgraph.generated.users.item.onenote import onenote_request_builder as user_onenote
from msgraph.generated.users.item.onenote.notebooks.item.notebook_item_request_builder import (
    NotebookItemRequestBuilder,
)
from msgraph.generated.users.item.onenote.notebooks.notebooks_request_builder import (
    NotebooksRequestBuilder,
)
from msgraph.generated.users.item.onenote.pages.item.onenote_page_item_request_builder import (
    OnenotePageItemRequestBuilder,
)
from msgraph.generated.users.item.onenote.pages.item.onenote_patch_content import (
    onenote_patch_content_post_request_body as _post_request_body,
)
from msgraph.generated.users.item.onenote.section_groups.item import (
    section_group_item_request_builder,
)
from msgraph.generated.users.item.onenote.sections.item import (
    onenote_section_item_request_builder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import (
    MAX_SCANNED_ITEMS,
    FetchedResponse,
    TypedQueryParameters,
    collect_pages,
    graph_step,
    no_retry,
    request_with_query,
)
from office_365_mcp.shared.handles import (
    OnenoteNotebookHandle,
    OnenoteOperationHandle,
    OnenoteOwner,
    OnenotePageHandle,
    OnenoteSectionGroupHandle,
    OnenoteSectionHandle,
)

PAGE_FIELDS: tuple[str, ...] = (
    "id",
    "title",
    "createdDateTime",
    "lastModifiedDateTime",
    "links",
    "createdByAppId",
)
PAGE_EXPANSIONS: tuple[str, ...] = ("parentSection", "parentNotebook")

NOTEBOOK_AUDIENCE_FIELDS: tuple[str, ...] = ("id", "displayName", "isShared", "userRole")
_DEFAULT_NOTEBOOK_FIELDS: tuple[str, ...] = (*NOTEBOOK_AUDIENCE_FIELDS, "isDefault")

STEP_NOTEBOOK = "notebook"
STEP_SECTION = "section"
STEP_SECTION_GROUP = "section_group"
STEP_NOTEBOOKS = "notebooks"
STEP_PAGE = "page"

_NotebookQuery = NotebookItemRequestBuilder.NotebookItemRequestBuilderGetQueryParameters
_NotebooksQuery = NotebooksRequestBuilder.NotebooksRequestBuilderGetQueryParameters
_SectionItemBuilder = onenote_section_item_request_builder.OnenoteSectionItemRequestBuilder
_SectionQuery = _SectionItemBuilder.OnenoteSectionItemRequestBuilderGetQueryParameters
_SectionGroupItemBuilder = section_group_item_request_builder.SectionGroupItemRequestBuilder
_SectionGroupQuery = _SectionGroupItemBuilder.SectionGroupItemRequestBuilderGetQueryParameters
_PageQuery = OnenotePageItemRequestBuilder.OnenotePageItemRequestBuilderGetQueryParameters

type OnenoteRoot = (
    user_onenote.OnenoteRequestBuilder
    | group_onenote.OnenoteRequestBuilder
    | site_onenote.OnenoteRequestBuilder
)


def onenote_root(client: GraphServiceClient, owner: OnenoteOwner | None) -> OnenoteRoot:
    if owner is None:
        return client.me.onenote
    match owner.kind:
        case "groups":
            return client.groups.by_group_id(owner.owner_id).onenote
        case "sites":
            return client.sites.by_site_id(owner.owner_id).onenote
        case _:
            assert_never(owner.kind)


def owner_named(*, group: str | None, site: str | None) -> OnenoteOwner | None:
    assert group is None or site is None, "a OneNote item belongs to a group or a site, not both"
    if group is not None:
        return OnenoteOwner("groups", group)
    if site is not None:
        return OnenoteOwner("sites", site)
    return None


def in_a_site(*owners: OnenoteOwner | None) -> bool:
    return any(owner is not None and owner.kind == "sites" for owner in owners)


OWNED_REFUSED = (
    "Microsoft 365 refused this request for a notebook that a Microsoft 365 group or a "
    + "SharePoint site owns. Most likely, the signed-in user is not a member of that group or "
    + "site. Ask the user to get access. If the user already has access, ask a Microsoft 365 "
    + "administrator to examine the OneNote permissions of this connector. This same call fails "
    + "again, so do not retry it."
)


def group_id_of(owner: OnenoteOwner | None) -> str | None:
    return owner.owner_id if owner is not None and owner.kind == "groups" else None


async def get_with_query[M: Parsable](
    client: GraphServiceClient,
    builder: BaseRequestBuilder,
    typed: TypedQueryParameters,
    model: ParsableFactory[M],
    *,
    query: Mapping[str, str] | None = None,
) -> M | None:
    request = request_with_query(
        Method.GET,
        builder.url_template,
        builder.path_parameters,
        query={} if query is None else query,
        typed=typed,
    )
    request.headers.try_add("Accept", "application/json")
    return await client.request_adapter.send_async(  # pyright: ignore[reportUnknownMemberType]
        request, model, {"XXX": ODataError}
    )


async def patch_page(
    client: GraphServiceClient,
    handle: OnenotePageHandle,
    commands: Sequence[OnenotePatchContentCommand],
    *,
    safe_to_repeat: bool,
) -> None:
    patch = (
        onenote_root(client, handle.owner)
        .pages.by_onenote_page_id(handle.page_id)
        .onenote_patch_content
    )
    request = RequestInformation(Method.POST, patch.url_template, patch.path_parameters)
    request.headers.try_add("Accept", "application/json")
    request.set_content_from_parsable(  # pyright: ignore[reportUnknownMemberType]
        client.request_adapter,  # pyright: ignore[reportUnknownMemberType]
        "application/json",
        _post_request_body.OnenotePatchContentPostRequestBody(commands=list(commands)),
    )
    if not safe_to_repeat:
        request.add_request_options(no_retry())
    await client.request_adapter.send_no_response_content_async(  # pyright: ignore[reportUnknownMemberType]
        request, {"XXX": ODataError}
    )


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


ContainerOrderBy = Literal[
    "name_asc",
    "name_desc",
    "created_desc",
    "created_asc",
    "last_modified_desc",
    "last_modified_asc",
]

CONTAINER_ORDER_CLAUSES: Mapping[ContainerOrderBy, str] = {
    "name_asc": "displayName asc",
    "name_desc": "displayName desc",
    "created_desc": "createdDateTime desc",
    "created_asc": "createdDateTime asc",
    "last_modified_desc": "lastModifiedDateTime desc",
    "last_modified_asc": "lastModifiedDateTime asc",
}


class _Created(Protocol):
    @property
    def created_by(self) -> IdentitySet | None: ...


def creator_name_of(identity: IdentitySet | None) -> str | None:
    if identity is None or identity.user is None:
        return None
    return identity.user.display_name


def created_by_contains(fragment: str) -> Callable[[_Created], bool]:
    wanted = fragment.casefold()

    def created_by_matches(item: _Created) -> bool:
        name = creator_name_of(item.created_by)
        return name is not None and wanted in name.casefold()

    return created_by_matches


class PageSummary(BaseModel):
    uri: str = Field(
        description=(
            "This page's handle: onenote:///pages/{id}, with the id percent-encoded. A handle from "
            + "a group or site notebook starts with onenote:///groups/{group}/ or "
            + "onenote:///sites/{site}/ instead. Pass it word for word to onenote_read_page to "
            + "read the page, or to onenote_append_to_page to add to it. Never build one: a page "
            + "id alone reaches nothing."
        )
    )
    title: str | None = Field(
        description=(
            "The page title as the page index holds it. Null when the page has none. The page "
            + "index can lag a create or an edit by days, so a new or changed page can show no "
            + "title here for days. onenote_read_page shows the true title from the start."
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
            + "listing of pages orders by this field, newest change first. The page index can lag "
            + "an edit, so a page written moments ago can still show the earlier value here."
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
            "If the person has the OneNote desktop app installed, this address opens the page "
            + "there."
        )
    )
    section_uri: str | None = Field(
        description=(
            "The handle of the section that holds this page: onenote:///sections/{id}. A handle "
            + "from a group or site notebook starts with onenote:///groups/{group}/ or "
            + "onenote:///sites/{site}/ instead. Pass it to onenote_list_pages to see this page's "
            + "siblings, or to onenote_create_page to add a page beside it. Null when Graph named "
            + "no parent section for this page."
        )
    )
    section_name: str | None = Field(
        description=(
            "The display name of the section that holds this page. Null when Graph named no "
            + "parent section."
        )
    )
    notebook_name: str | None = Field(
        description=(
            "The display name of the notebook that holds this page. Null when Graph named no "
            + "parent notebook."
        )
    )
    level: int | None = Field(
        description=(
            "How deeply this page is indented under another page in its section. Level 0 is a "
            + "top-level page, and each deeper level adds 1. This is null unless "
            + "onenote_list_pages sets include_level_and_order=true."
        )
    )
    order: int | None = Field(
        description=(
            "Where this page sits among the other pages of its section, in Microsoft's own order. "
            + "This is null unless onenote_list_pages sets include_level_and_order=true."
        )
    )
    created_by_app_id: str | None = Field(
        description=(
            "The identifier of the app that created this page, as Graph reported it. Pass it as "
            + "`created_by_app_id` to onenote_list_pages to find the other pages that app "
            + "created. Null when Graph recorded none."
        )
    )

    @classmethod
    def from_page(cls, page: OnenotePage, *, owner: OnenoteOwner | None = None) -> Self | None:
        if page.id is None:
            return None
        section = page.parent_section
        section_id = section.id if section is not None else None
        notebook = page.parent_notebook
        return cls(
            uri=OnenotePageHandle(page.id, owner=owner).uri,
            title=page.title,
            created_at=page.created_date_time,
            last_modified_at=page.last_modified_date_time,
            web_url=web_url_of(page.links),
            client_url=client_url_of(page.links),
            section_uri=(
                None if section_id is None else OnenoteSectionHandle(section_id, owner=owner).uri
            ),
            section_name=section.display_name if section is not None else None,
            notebook_name=notebook.display_name if notebook is not None else None,
            level=page.level,
            order=page.order,
            created_by_app_id=page.created_by_app_id,
        )


async def page_summary(
    client: GraphServiceClient, page_id: str, *, owner: OnenoteOwner | None = None
) -> PageSummary:
    with graph_step(STEP_PAGE):
        found = await get_with_query(
            client,
            onenote_root(client, owner).pages.by_onenote_page_id(page_id),
            _PageQuery(select=list(PAGE_FIELDS), expand=list(PAGE_EXPANSIONS)),
            OnenotePage,
        )
    assert found is not None, "Graph answered a page re-read with no page"
    summary = PageSummary.from_page(found, owner=owner)
    assert summary is not None, "Graph re-read a page it gave no id, which cannot be addressed"
    return summary


OWNER_ROLE = "Owner"


@dataclass(frozen=True, slots=True)
class NotebookAudience:
    notebook_id: str | None
    name: str | None
    is_shared: bool | None
    user_role: str | None
    owner: OnenoteOwner | None = None

    @property
    def reaches_others(self) -> bool:
        return self.owner is not None or not (
            self.is_shared is False and self.user_role == OWNER_ROLE
        )

    @property
    def reason(self) -> str:
        if self.owner is not None:
            match self.owner.kind:
                case "groups":
                    return "which belongs to a Microsoft 365 group"
                case "sites":
                    return "which belongs to a SharePoint site"
                case _:
                    assert_never(self.owner.kind)
        if self.is_shared:
            return "which is shared with other people"
        if self.user_role is not None and self.user_role != OWNER_ROLE:
            return f"which belongs to somebody else (you are {self.user_role})"
        return "whose sharing Microsoft did not report"


def audience_of(notebook: Notebook, *, owner: OnenoteOwner | None = None) -> NotebookAudience:
    return NotebookAudience(
        notebook_id=notebook.id,
        name=notebook.display_name,
        is_shared=notebook.is_shared,
        user_role=(
            None
            if notebook.user_role is None
            else cast("str", cast("object", notebook.user_role.value))
        ),
        owner=owner,
    )


async def notebook_audience(
    client: GraphServiceClient, notebook_id: str, *, owner: OnenoteOwner | None = None
) -> NotebookAudience:
    with graph_step(STEP_NOTEBOOK):
        found = await get_with_query(
            client,
            onenote_root(client, owner).notebooks.by_notebook_id(notebook_id),
            _NotebookQuery(select=list(NOTEBOOK_AUDIENCE_FIELDS)),
            Notebook,
        )
    assert found is not None, "Graph answered a notebook read with no notebook"
    return audience_of(found, owner=owner)


async def default_notebook_audience(client: GraphServiceClient) -> NotebookAudience | None:
    with graph_step(STEP_NOTEBOOKS):
        first_page = await client.me.onenote.notebooks.get(
            request_configuration=RequestConfiguration[_NotebooksQuery](
                query_parameters=_NotebooksQuery(select=list(_DEFAULT_NOTEBOOK_FIELDS))
            )
        )
        assert first_page is not None, "Graph answered notebooks with no collection"
        collected = await collect_pages(first_page, client, limit=MAX_SCANNED_ITEMS)
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


_CONTAINER_FIELDS: tuple[str, ...] = ("id", "displayName")


@dataclass(frozen=True, slots=True)
class ContainerAudience:
    name: str | None
    notebook: NotebookAudience


async def _audience_of_notebook_id(
    client: GraphServiceClient, notebook_id: str | None, *, owner: OnenoteOwner | None
) -> NotebookAudience:
    if notebook_id is None:
        return replace(UNKNOWN_AUDIENCE, owner=owner)
    return await notebook_audience(client, notebook_id, owner=owner)


async def section_container(
    client: GraphServiceClient, section_id: str, *, owner: OnenoteOwner | None = None
) -> ContainerAudience:
    with graph_step(STEP_SECTION):
        found = await get_with_query(
            client,
            onenote_root(client, owner).sections.by_onenote_section_id(section_id),
            _SectionQuery(select=list(_CONTAINER_FIELDS), expand=["parentNotebook"]),
            OnenoteSection,
        )
    assert found is not None, "Graph answered a section read with no section"
    parent = found.parent_notebook
    notebook_id = parent.id if parent is not None else None
    return ContainerAudience(
        name=found.display_name,
        notebook=await _audience_of_notebook_id(client, notebook_id, owner=owner),
    )


async def section_group_container(
    client: GraphServiceClient, section_group_id: str, *, owner: OnenoteOwner | None = None
) -> ContainerAudience:
    with graph_step(STEP_SECTION_GROUP):
        found = await get_with_query(
            client,
            onenote_root(client, owner).section_groups.by_section_group_id(section_group_id),
            _SectionGroupQuery(select=list(_CONTAINER_FIELDS), expand=["parentNotebook"]),
            SectionGroup,
        )
    assert found is not None, "Graph answered a section group read with no section group"
    parent = found.parent_notebook
    notebook_id = parent.id if parent is not None else None
    return ContainerAudience(
        name=found.display_name,
        notebook=await _audience_of_notebook_id(client, notebook_id, owner=owner),
    )


async def section_audience(
    client: GraphServiceClient, section_id: str, *, owner: OnenoteOwner | None = None
) -> NotebookAudience:
    return (await section_container(client, section_id, owner=owner)).notebook


async def container_audience(
    client: GraphServiceClient, handle: OnenoteNotebookHandle | OnenoteSectionGroupHandle
) -> ContainerAudience:
    if isinstance(handle, OnenoteNotebookHandle):
        notebook = await notebook_audience(client, handle.notebook_id, owner=handle.owner)
        return ContainerAudience(name=notebook.name, notebook=notebook)
    return await section_group_container(client, handle.section_group_id, owner=handle.owner)


_PAGE_FOR_A_QUESTION_FIELDS: tuple[str, ...] = ("id", "title")
_PAGE_FOR_A_QUESTION_EXPANSIONS: tuple[str, ...] = ("parentNotebook", "parentSection")


@dataclass(frozen=True, slots=True)
class PageForAQuestion:
    page: OnenotePage
    audience: NotebookAudience


async def page_for_a_question(
    client: GraphServiceClient, page_id: str, *, owner: OnenoteOwner | None = None
) -> PageForAQuestion:
    with graph_step(STEP_PAGE):
        found = await get_with_query(
            client,
            onenote_root(client, owner).pages.by_onenote_page_id(page_id),
            _PageQuery(
                select=list(_PAGE_FOR_A_QUESTION_FIELDS),
                expand=list(_PAGE_FOR_A_QUESTION_EXPANSIONS),
            ),
            OnenotePage,
        )
    assert found is not None, "Graph answered a page read with no page"
    parent = found.parent_notebook
    notebook_id = parent.id if parent is not None else None
    return PageForAQuestion(
        page=found,
        audience=await _audience_of_notebook_id(client, notebook_id, owner=owner),
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
    owner = owner_of_graph_url(location)
    kind = _RESOURCE_KIND_OF[family]
    if family == "pages":
        return OnenotePageHandle(resolved_id, owner=owner).uri, kind
    if family == "sections":
        return OnenoteSectionHandle(resolved_id, owner=owner).uri, kind
    return OnenoteNotebookHandle(resolved_id, owner=owner).uri, kind


_OWNER_ROOT = re.compile(r"/(groups|sites)(?:/([^/]+)|\('([^'/]+)'\))/onenote/")


def owner_of_graph_url(url: str) -> OnenoteOwner | None:
    match = _OWNER_ROOT.search(urlsplit(url).path)
    if match is None:
        return None
    kind, segment, key = match.groups()
    owner_id = unquote(segment if segment is not None else key)
    if not owner_id.strip():
        return None
    return OnenoteOwner("groups" if kind == "groups" else "sites", owner_id)


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
            + "A handle from a group or site notebook starts with onenote:///groups/{group}/ or "
            + "onenote:///sites/{site}/ instead. Pass it to onenote_get_operation, and use that "
            + "same handle for every poll. A later poll's own `uri` differs, because Microsoft "
            + "appends the caller's id, so do not reuse it. Never build one: an operation id "
            + "alone reaches nothing."
        )
    )
    status: OperationState | None = Field(
        description=(
            "Microsoft's own status word for this operation: NotStarted, Running, Completed or "
            + "Failed. Null right after Microsoft accepts a copy, before it reports any status. "
            + "Poll onenote_get_operation with `uri` to fill it in. Poll again until it reads "
            + "Completed or Failed."
        )
    )
    percent_complete: str | None = Field(
        description=(
            "Graph's own estimate of how much of the operation is done, as the digits of a "
            + "percentage. Microsoft reports this as text, not a number. Null while Graph has "
            + "nothing to report."
        )
    )
    created_at: datetime | None = Field(
        description=(
            "When the operation started, as Graph reported it. Null when Graph recorded " + "none."
        )
    )
    last_action_at: datetime | None = Field(
        description=("When Graph last acted on this operation. Null when Graph recorded none.")
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
    def from_operation(cls, op: OnenoteOperation, *, owner: OnenoteOwner | None = None) -> Self:
        assert op.id is not None, "Graph answered with an operation that has no id"
        result = resource_handle_of(op.resource_location, op.resource_id)
        result_uri, result_kind = result if result is not None else (None, None)
        error = op.error
        return cls(
            uri=OnenoteOperationHandle(op.id, owner=owner).uri,
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
    def accepted(cls, operation_id: str, *, owner: OnenoteOwner | None = None) -> Self:
        return cls(
            uri=OnenoteOperationHandle(operation_id, owner=owner).uri,
            status=None,
            percent_complete=None,
            created_at=None,
            last_action_at=None,
            result_uri=None,
            result_kind=None,
            error_code=None,
            error_message=None,
        )


_JSON_MEDIA_TYPE = "application/json"


def accepted_operation(
    fetched: FetchedResponse, *, owner: OnenoteOwner | None = None
) -> OperationSummary | None:
    if fetched.content and fetched.media_type == _JSON_MEDIA_TYPE:
        node = JsonParseNodeFactory().get_root_parse_node(_JSON_MEDIA_TYPE, fetched.content)
        operation = node.get_object_value(OnenoteOperation)
        if operation.id is not None:
            return OperationSummary.from_operation(operation, owner=owner)
    operation_id = operation_id_in(fetched.headers.get("operation-location"))
    if operation_id is None:
        return None
    return OperationSummary.accepted(operation_id, owner=owner)


def write_state_for(*parts: str) -> str:
    return sha256("\x1f".join(parts).encode()).hexdigest()
