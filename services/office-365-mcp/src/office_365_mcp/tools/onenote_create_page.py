from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from html import escape
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.method import Method
from kiota_abstractions.request_information import RequestInformation
from mcp.types import InputRequiredResult
from msgraph.generated.models.o_data_errors.o_data_error import ODataError
from msgraph.generated.models.onenote_page import OnenotePage
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.handles import (
    OnenotePageHandle,
    OnenoteSectionHandle,
    onenote_section_handle,
)
from office_365_mcp.shared.notes import (
    UNKNOWN_AUDIENCE,
    NotebookAudience,
    client_url_of,
    default_notebook_audience,
    section_audience,
    web_url_of,
    write_state_for,
)
from office_365_mcp.shared.prose import body_opening
from office_365_mcp.shared.seam import (
    WRITE_ADDITIVE,
    Confirm,
    answer_pending,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "onenote_create_page"

STEP_CREATE = "create_page"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Notes.Create",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "title": "Synthetic note",
    "body_html": "<p>Synthetic body.</p>",
}

MAX_TITLE_CHARACTERS = 255

MAX_BODY_CHARACTERS = 500_000

GRAPH_NOT_FOUND = (
    "Microsoft 365 will not create this page. If this call named a `section`, the handle is well "
    + "formed, so the section was most likely deleted, moved into a different notebook, which "
    + "gives it a new handle, or the notebook holding it could not be read: call "
    + "onenote_list_notebooks again and take a fresh `uri` for the section from that result, "
    + "because this same handle fails the same way again. If it named "
    + "none, the request went to the user's own default notebook, and Microsoft reports it has no "
    + "such thing, which most often means OneNote has never been set up for this account. No "
    + "other argument here fixes that: tell the user to open OneNote once, then try again later."
)

_NOT_A_SECTION_HANDLE = (
    "onenote_create_page takes a section handle in `section`, if it is given at all. It looks "
    + "like onenote:///sections/{id}, and it comes from the `uri` of a section in an "
    + "onenote_list_notebooks result. Copy it exactly. A section name is not a handle, and "
    + "neither is a notebook name, a path, a web address or a bare id. Omit `section` entirely "
    + "to create the page in the default section of the default notebook instead."
)

_DESCRIPTION = """\
Write a brand-new page into the signed-in user's own OneNote, right now. This is not a draft: \
there is no review step, nobody approves it first, and the page exists in the notebook the \
moment this tool returns. This connector sends no notification when it creates the page, and \
Microsoft Graph sends none for it either, but OneNote itself can show the new page to people \
who open the notebook. This tool asks the person at the other end to confirm before writing \
when the notebook is shared with other people or belongs to somebody else, or when Microsoft \
does not report who can see it, because the page is visible to them the moment it is written. \
A page in the user's own unshared notebook is written without a question. Pass a `section` \
handle from onenote_list_notebooks to choose which section holds the new page; omit `section` \
and Microsoft creates it in the default section of the default notebook instead. `body_html` \
is HTML, not \
plain text: a newline in it is not a line break. Write `<p>` and `<br>` for structure, \
`<h1>` through `<h6>` for headings, `<ul>`/`<ol>`/`<li>` for lists, `<table>` for a table, and \
`<b>`/`<i>` for emphasis. Microsoft removes JavaScript, CSS and HTML forms from what is sent. \
Escape `&`, `<` and `>` in `body_html` wherever they must read as themselves rather than as \
markup. This tool places `title` in the page's own `<head><title>`, and `body_html` becomes the \
page body exactly as sent. **There is no way to attach a file or an image here, and \
that absence is deliberate.** This connector has no content store, and it fetches nothing a \
model names: accepting a URL or a file id here would have this pod pull content from wherever \
the model pointed it, into a page written under this user's name. To add more content to a page \
that already exists — including one this call just created — use onenote_append_to_page \
instead; it cannot attach a file either. If this call times out, do not simply call it again: \
Microsoft may already have created the page before the response was lost, and calling again \
writes a second, duplicate page. List the section's pages with onenote_list_pages first: a page \
created moments ago is listed at once but can show an empty title for a long time (days on a \
test tenant), so judge by `created_at` and the count rather than by title, and call this again \
only once you have confirmed the page is not there. The answer's \
`title` is what Microsoft actually stored, read back off its response rather than echoed from \
the argument — read it to the user so they know what the page is really called.\
"""


class CreatedPage(BaseModel):
    uri: str = Field(
        description=(
            "This new page's handle: onenote:///pages/{id}, with the id percent-encoded. Pass "
            + "it to onenote_read_page to read the page back, or to onenote_append_to_page to "
            + "add more to it."
        )
    )
    title: str | None = Field(
        description=(
            "The title Microsoft actually stored for this page, read off its response rather "
            + "than echoed from the `title` argument. Read it back to the user: it is the "
            + "record of what the page is really called."
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
    created_at: datetime | None = Field(
        description="When Microsoft recorded creating this page. Null when Graph reported none."
    )
    section_uri: str | None = Field(
        description=(
            "The handle of the section this page was written into: onenote:///sections/{id}. "
            + "This is the `section` argument's own handle when one was given, unless "
            + "Microsoft's response itself names a different parent section, which takes "
            + "priority over the argument. Null when `section` was omitted and Microsoft's "
            + "response named no parent section either — pass onenote_list_pages no `section` "
            + "to find the page by looking through every notebook."
        )
    )


def _now() -> datetime:
    return datetime.now(UTC)


_CREATE = "create"
_DO_NOT_CREATE = "do not create"
_NOTHING_CREATED = "No page was created."


async def _notebook_audience_for(
    client: GraphServiceClient, handle: OnenoteSectionHandle | None
) -> NotebookAudience | None:
    if handle is None:
        return await default_notebook_audience(client)
    return await section_audience(client, handle.section_id)


def _question(title: str, body_html: str, audience: NotebookAudience) -> str:
    name = audience.name or "an unnamed notebook"
    return (
        f"Create the page {title!r} in the notebook {name!r}, {audience.reason}? "
        + f"It opens {body_opening(body_html)!r}."
    )


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(
        ctx, agree=_CREATE, decline=_DO_NOT_CREATE, nothing_happened=_NOTHING_CREATED
    )


async def create_page(
    client: GraphServiceClient,
    *,
    title: str,
    body_html: str,
    section: str | None = None,
    now: Callable[[], datetime] = _now,
    confirm: Confirm,
    answer_pending: bool = False,
) -> CreatedPage | InputRequiredResult:
    assert 1 <= len(title) <= MAX_TITLE_CHARACTERS, (
        f"title is bounded by the schema, got {len(title)}"
    )
    assert 1 <= len(body_html) <= MAX_BODY_CHARACTERS, (
        f"body_html is bounded by the schema, got {len(body_html)}"
    )
    handle = _section_to_write_to(section)
    html_bytes = _envelope(title, body_html, now()).encode("utf-8")

    pages = (
        client.me.onenote.pages
        if handle is None
        else client.me.onenote.sections.by_onenote_section_id(handle.section_id).pages
    )
    request = RequestInformation(Method.POST, pages.url_template, pages.path_parameters)
    request.headers.try_add("Accept", "application/json")
    request.set_stream_content(html_bytes, "text/html")
    request.add_request_options(no_retry())

    about = write_state_for("create", handle.section_id if handle else "default", title, body_html)
    created: OnenotePage | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors(TOOL_NAME):
        audience = await _notebook_audience_for(client, handle)
        if answer_pending or (audience is not None and audience.reaches_others):
            heard_by = audience if audience is not None else UNKNOWN_AUDIENCE
            with not_graph():
                answer = await confirm(_question(title, body_html, heard_by), about)
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with graph_step(STEP_CREATE):
                created = await client.request_adapter.send_async(  # pyright: ignore[reportUnknownMemberType]
                    request, OnenotePage, {"XXX": ODataError}
                )

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert created is not None, "Graph answered a page create with no page"
    return _answer(created, handle)


def _section_to_write_to(section: str | None) -> OnenoteSectionHandle | None:
    if section is None:
        return None
    handle = onenote_section_handle(section)
    if handle is None:
        raise ToolError(_NOT_A_SECTION_HANDLE)
    return handle


def _envelope(title: str, body_html: str, created_at: datetime) -> str:
    return (
        "<!DOCTYPE html><html><head><title>"
        + escape(title)
        + '</title><meta name="created" content="'
        + created_at.isoformat(timespec="seconds")
        + '" /></head><body>'
        + body_html
        + "</body></html>"
    )


def _answer(page: OnenotePage, handle: OnenoteSectionHandle | None) -> CreatedPage:
    assert page.id is not None, "Graph created a page it gave no id, which cannot be addressed"
    parent = page.parent_section
    parent_id = parent.id if parent is not None else None
    if parent_id is not None:
        section_uri = OnenoteSectionHandle(parent_id).uri
    elif handle is not None:
        section_uri = handle.uri
    else:
        section_uri = None
    return CreatedPage(
        uri=OnenotePageHandle(page.id).uri,
        title=page.title,
        web_url=web_url_of(page.links),
        client_url=client_url_of(page.links),
        created_at=page.created_date_time,
        section_uri=section_uri,
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Create a Page",
        description=_DESCRIPTION,
        annotations=WRITE_ADDITIVE,
    )
    async def onenote_create_page(
        title: Annotated[
            str,
            Field(
                min_length=1,
                max_length=MAX_TITLE_CHARACTERS,
                description=(
                    "The new page's title, as the user wrote it. This tool places it in the "
                    + "page's own `<head><title>`; the answer's `title` is what Microsoft "
                    + "actually stored, so read that back rather than assuming it equals this "
                    + "argument."
                ),
            ),
        ],
        body_html: Annotated[
            str,
            Field(
                min_length=1,
                max_length=MAX_BODY_CHARACTERS,
                description=(
                    f"The page content, as HTML, up to {MAX_BODY_CHARACTERS:,} characters "
                    + "(Microsoft Graph refuses a request over 4 MB regardless). A newline is "
                    + "not a line break: write `<p>` and `<br>` for structure, `<h1>` through "
                    + "`<h6>` for headings, `<ul>`/`<ol>`/`<li>` for lists, `<table>` for a "
                    + "table, and `<b>`/`<i>` for emphasis. Microsoft removes JavaScript, CSS "
                    + "and HTML forms from what is sent. Escape `&`, `<` and `>` wherever they "
                    + "must read as themselves rather than as markup. There is no way to include "
                    + "an image or a file here."
                ),
            ),
        ],
        ctx: Context,
        section: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The section to create the page in, as the `uri` of a section from an "
                    + "onenote_list_notebooks result: onenote:///sections/{id}. Omit it to "
                    + "create the page in the default section of the default notebook instead. "
                    + "A section name, a notebook name and a web address are none of them a "
                    + "handle."
                ),
            ),
        ] = None,
        client: GraphServiceClient = graph,
    ) -> CreatedPage | InputRequiredResult:
        return await create_page(
            client,
            title=title,
            body_html=body_html,
            section=section,
            confirm=a_person_agrees(ctx),
            answer_pending=answer_pending(ctx),
        )
