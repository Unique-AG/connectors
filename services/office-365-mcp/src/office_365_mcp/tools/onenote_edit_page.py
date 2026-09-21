import json
from collections.abc import Mapping
from typing import Annotated, Literal, Self

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.onenote_page import OnenotePage
from msgraph.generated.models.onenote_patch_action_type import OnenotePatchActionType
from msgraph.generated.models.onenote_patch_content_command import OnenotePatchContentCommand
from msgraph.generated.models.onenote_patch_insert_position import OnenotePatchInsertPosition
from msgraph.generated.users.item.onenote.pages.item.onenote_page_item_request_builder import (
    OnenotePageItemRequestBuilder,
)
from msgraph.generated.users.item.onenote.pages.item.onenote_patch_content import (
    onenote_patch_content_post_request_body as _post_request_body,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field, model_validator

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.handles import OnenotePageHandle, onenote_page_handle
from office_365_mcp.shared.notes import (
    PAGE_EXPANSIONS,
    PAGE_FIELDS,
    UNKNOWN_AUDIENCE,
    NotebookAudience,
    PageSummary,
    notebook_audience,
    write_state_for,
)
from office_365_mcp.shared.prose import body_opening
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE,
    Confirm,
    answer_pending,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "onenote_edit_page"

STEP_PAGE = "page"
STEP_EDIT_CONTENT = "edit_content"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Notes.ReadWrite",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "page": "onenote:///pages/1-SYNTHETICPAGE00000000000000000000%21ABCDEF",
    "commands": [{"target": "body", "action": "append", "content": "<p>Synthetic.</p>"}],
}

MAX_COMMANDS = 20
MAX_TARGET_CHARACTERS = 500
MAX_CONTENT_CHARACTERS = 500_000

_PageQuery = OnenotePageItemRequestBuilder.OnenotePageItemRequestBuilderGetQueryParameters

_AUDIENCE_PAGE_FIELDS: tuple[str, ...] = ("id", "title")
_AUDIENCE_PAGE_EXPANSIONS: tuple[str, ...] = ("parentNotebook",)

_ACTION_TYPES: Mapping[str, OnenotePatchActionType] = {
    "append": OnenotePatchActionType.Append,
    "insert": OnenotePatchActionType.Insert,
    "prepend": OnenotePatchActionType.Prepend,
    "replace": OnenotePatchActionType.Replace,
    "delete": OnenotePatchActionType.Delete,
}

_POSITIONS: Mapping[str, OnenotePatchInsertPosition] = {
    "before": OnenotePatchInsertPosition.Before,
    "after": OnenotePatchInsertPosition.After,
}

_DESTRUCTIVE_ACTIONS = ("replace", "delete")

_EDIT = "edit"
_DO_NOT_EDIT = "do not edit"
_NOTHING_CHANGED = "Nothing was changed."

_UNTITLED_PAGE = "an untitled page"
_UNNAMED_NOTEBOOK = "an unnamed notebook"

_DESCRIPTION = """\
Change what is already on an existing OneNote page: add content next to something, replace an \
element outright, or delete one. Pass the `page` handle from a onenote_list_pages row or a \
onenote_create_page answer, and one to twenty `commands` to run against it in order. Each \
command names a `target` (an element on the page: `body`, `title`, a `#data-id` written in the \
page's own HTML, or a generated id from onenote_read_page with `include_ids=true` — a generated \
id is passed bare with no `#` in front of it, while a `data-id` needs the `#` kept in front) and \
an `action`: `append` adds `content` as a new child of `target`, last by default or first when \
`position` is `before`; `prepend` is a shortcut for append-before, always adding `content` as \
the first child; `insert` adds `content` as a new sibling of `target`, after it by default or \
before it when `position` is `before`; `replace` throws away everything `target` held and puts \
`content` there instead; `delete` removes `target` outright and takes no `content` at all — a \
command with `action` set to `delete` and a `content` value is refused before this reaches \
Microsoft. `position` only changes anything for `insert` (before or after the target) and for \
`append` on a list or the page body (first child or last child); everywhere else it is ignored, \
and Microsoft's own default is `after`. Not every element accepts every action: the page `body` \
(which is really its first div) takes `append` only; a `div` takes `replace`, `append` and \
`insert`; an `img` or an `object` takes `replace` and `insert` but never `append`; an `ol` or a \
`ul` takes `replace`, `append` and `insert`; a `table` takes `replace` and `insert` but never \
`append`; a `p`, an `li`, or a heading `h1` through `h6` takes `replace` and `insert` but never \
`append`; the page `title` takes `replace` only — use onenote_rename_page for that instead of \
spending a command here. Microsoft accepts no update at all against an absolutely positioned \
`img` or `object`, a `tr`, a `td`, `meta`, `head`, `span`, `a`, or a `style` tag: naming one of \
those as `target` is refused by Microsoft, not by this tool. A `replace` or a `delete` command \
erases something that was on the page, so this tool ALWAYS asks the person at the other end to \
confirm before running any command set that contains one, on top of asking whenever the page's \
notebook is shared with other people, belongs to somebody else, or Microsoft does not report \
who can see it. A command set with no `replace` and no `delete`, into the user's own unshared \
notebook, runs without a question. This call is NOT SAFE TO RETRY BLINDLY: if it times out, \
Microsoft may already hold the change, and calling it again with the same commands can apply an \
append or an insert a second time, or fail a replace or a delete that already succeeded because \
the target it named is gone. On a timeout, read the page first with onenote_read_page and \
compare it against what these commands were meant to do before calling this again. This tool \
answers with the page as Microsoft's page index holds it right after the write. That index lags \
an edit, by minutes or far longer, so `last_modified_at` and `title` in the answer can still \
show the values from before this write while onenote_read_page already returns the change.\
"""

_NOT_A_PAGE_HANDLE = (
    "onenote_edit_page takes a page handle. It looks like onenote:///pages/{id}, with the id "
    + "percent-encoded, for example "
    + "onenote:///pages/1-SYNTHETICPAGE00000000000000000000%21ABCDEF. A section handle "
    + "(onenote:///sections/{id}) is not a page handle: it names a whole section, not one page "
    + "inside it. A page title, a web address, and a bare id with no scheme are not handles "
    + "either. Take the `uri` from a onenote_list_pages row or a onenote_create_page answer, "
    + "and copy it word for word. This same value fails again, so do not retry it."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 could not complete this edit. The handle is well formed, so the argument is "
    + "not the problem. The page was most likely deleted or moved to another section, either of "
    + "which gives it a new id that this handle does not name — or the notebook holding the "
    + "page could not be read. Either way, nothing was changed. Find the page again with "
    + "onenote_list_pages, and take the `uri` from that new result. This same handle fails the "
    + "same way every time, so do not retry it."
)


class EditCommand(BaseModel):
    target: str = Field(
        min_length=1,
        max_length=MAX_TARGET_CHARACTERS,
        description=(
            "The element to change: `body` (the page's first div), `title` (the page title — "
            + "use onenote_rename_page instead of spending a command on it), a `#data-id` "
            + "written in the page's own input HTML with the `#` kept in front of it, or a "
            + "generated id from a onenote_read_page call made with `include_ids=true`, passed "
            + "with no `#` in front. Do not confuse a generated id with one written in the HTML "
            + "by hand: Microsoft discards every id it did not generate itself."
        ),
    )
    action: Literal["append", "insert", "prepend", "replace", "delete"] = Field(
        description=(
            "What to do at `target`: `append` adds `content` as a new child of `target`, last "
            + "by default or first when `position` is `before`; `prepend` is a shortcut for "
            + "append-before; `insert` adds `content` as a new sibling of `target`; `replace` "
            + "throws away what `target` held and puts `content` there instead; `delete` "
            + "removes `target` outright and takes no `content`. Not every element accepts "
            + "every action — this tool's own description carries the full table."
        ),
    )
    position: Literal["before", "after"] | None = Field(
        default=None,
        description=(
            "Where to put `content` relative to `target`: for `insert`, before or after the "
            + "target; for `append` on a list or the page body, first child or last child. "
            + "Microsoft's own default is `after`. Ignored by every other action."
        ),
    )
    content: str | None = Field(
        default=None,
        max_length=MAX_CONTENT_CHARACTERS,
        description=(
            "The well-formed HTML to add, or to replace `target` with. Escape `&`, `<` and `>` "
            + "where they must read as themselves rather than as markup. Required for every "
            + "action except `delete`, which takes none — a delete command that carries "
            + "content is refused before this reaches Microsoft."
        ),
    )

    @model_validator(mode="after")
    def _content_matches_the_action(self) -> Self:
        if self.action == "delete":
            if self.content is not None:
                raise ValueError(
                    "a delete command takes no content: it removes the target outright, it "
                    + "does not replace it with anything"
                )
        elif self.content is None:
            raise ValueError(
                f"a {self.action} command needs content: the HTML to put at the target"
            )
        return self


async def edit_page(
    client: GraphServiceClient,
    *,
    page: str,
    commands: list[EditCommand],
    confirm: Confirm,
    answer_pending: bool = False,
) -> PageSummary | InputRequiredResult:
    assert 1 <= len(commands) <= MAX_COMMANDS, (
        f"commands is bounded by the schema, got {len(commands)}"
    )
    handle = onenote_page_handle(page)
    if handle is None:
        raise ToolError(_NOT_A_PAGE_HANDLE)

    about = write_state_for(
        _EDIT,
        handle.page_id,
        json.dumps([command.model_dump() for command in commands], sort_keys=True),
    )
    destructive = any(command.action in _DESTRUCTIVE_ACTIONS for command in commands)
    refreshed: OnenotePage | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors(TOOL_NAME):
        with graph_step(STEP_PAGE):
            for_audience = await _page_for_audience(client, handle)
        audience = await _audience_of(client, for_audience)
        if answer_pending or audience.reaches_others or destructive:
            with not_graph():
                answer = await confirm(
                    _question(for_audience, audience, commands, destructive=destructive), about
                )
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with graph_step(STEP_EDIT_CONTENT):
                await _edit(client, handle, commands)
            with graph_step(STEP_PAGE):
                refreshed = await _page(client, handle)

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert refreshed is not None, "a write neither asked about nor refused wrote nothing"
    summary = PageSummary.from_page(refreshed)
    assert summary is not None, "Graph re-read a page it gave no id, which cannot be addressed"
    return summary


async def _audience_of(client: GraphServiceClient, page: OnenotePage) -> NotebookAudience:
    parent = page.parent_notebook
    notebook_id = parent.id if parent is not None else None
    if notebook_id is None:
        return UNKNOWN_AUDIENCE
    return await notebook_audience(client, notebook_id)


def _question(
    page: OnenotePage,
    audience: NotebookAudience,
    commands: list[EditCommand],
    *,
    destructive: bool,
) -> str:
    title = page.title or _UNTITLED_PAGE
    name = audience.name or _UNNAMED_NOTEBOOK
    reason = f", {audience.reason}" if audience.reaches_others else ""
    first = commands[0]
    opening = f" with text opening {body_opening(first.content)!r}" if first.content else ""
    count = "1 command" if len(commands) == 1 else f"{len(commands)} commands"
    warning = " A replace or a delete cannot be undone." if destructive else ""
    return (
        f"Change the page {title!r} in the notebook {name!r}{reason}? {count}; the first "
        + f"{first.action}s {first.target!r}{opening}.{warning}"
    )


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(
        ctx, agree=_EDIT, decline=_DO_NOT_EDIT, nothing_happened=_NOTHING_CHANGED
    )


async def _page_for_audience(client: GraphServiceClient, handle: OnenotePageHandle) -> OnenotePage:
    page = await client.me.onenote.pages.by_onenote_page_id(handle.page_id).get(
        request_configuration=RequestConfiguration[_PageQuery](
            query_parameters=_PageQuery(
                select=list(_AUDIENCE_PAGE_FIELDS), expand=list(_AUDIENCE_PAGE_EXPANSIONS)
            )
        )
    )
    assert page is not None, "Graph answered a page read with no page"
    return page


async def _edit(
    client: GraphServiceClient, handle: OnenotePageHandle, commands: list[EditCommand]
) -> None:
    body = _post_request_body.OnenotePatchContentPostRequestBody(
        commands=[
            OnenotePatchContentCommand(
                target=command.target,
                action=_ACTION_TYPES[command.action],
                position=None if command.position is None else _POSITIONS[command.position],
                content=command.content,
            )
            for command in commands
        ]
    )
    await client.me.onenote.pages.by_onenote_page_id(handle.page_id).onenote_patch_content.post(
        body,
        request_configuration=RequestConfiguration[QueryParameters](options=no_retry()),
    )


async def _page(client: GraphServiceClient, handle: OnenotePageHandle) -> OnenotePage:
    page = await client.me.onenote.pages.by_onenote_page_id(handle.page_id).get(
        request_configuration=RequestConfiguration[_PageQuery](
            query_parameters=_PageQuery(select=list(PAGE_FIELDS), expand=list(PAGE_EXPANSIONS))
        )
    )
    assert page is not None, "Graph answered a page re-read with no page"
    return page


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Edit a Page",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE,
    )
    async def onenote_edit_page(
        page: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The handle of the page to change, from a onenote_list_pages row or a "
                    + "onenote_create_page answer: `uri`, copied word for word. The shape is "
                    + "onenote:///pages/{id}. A section handle, onenote:///sections/{id}, is "
                    + "not a page handle. Never build one yourself: a page id alone, without "
                    + "this connector's scheme around it, reaches nothing."
                ),
            ),
        ],
        commands: Annotated[
            list[EditCommand],
            Field(
                min_length=1,
                max_length=MAX_COMMANDS,
                description=(
                    "One to twenty changes to run against the page, in order. Each is applied "
                    + "as its own Graph PATCH command inside the same request; Microsoft "
                    + "accepts or refuses the whole set together, so if one command names an "
                    + "element that does not accept its action, no command in the set is "
                    + "applied."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> PageSummary | InputRequiredResult:
        return await edit_page(
            client,
            page=page,
            commands=commands,
            confirm=a_person_agrees(ctx),
            answer_pending=answer_pending(ctx),
        )
