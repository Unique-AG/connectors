import json
from collections.abc import Mapping
from typing import Annotated, Literal

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
from msgraph.generated.users.item.onenote.pages.item.onenote_patch_content import (
    onenote_patch_content_post_request_body as _post_request_body,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import GraphFailure, graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.handles import OnenotePageHandle, onenote_page_handle
from office_365_mcp.shared.notes import (
    NotebookAudience,
    PageSummary,
    page_for_a_question,
    page_summary,
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

STEP_EDIT_CONTENT = "edit_content"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Notes.ReadWrite",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "page": "onenote:///pages/1-SYNTHETICPAGE00000000000000000000%21ABCDEF",
    "commands": [{"target": "body", "action": "append", "content": "<p>Synthetic.</p>"}],
}

MAX_COMMANDS = 20
MAX_TARGET_CHARACTERS = 500
MAX_CONTENT_CHARACTERS = 500_000

type _Action = Literal["append", "insert", "prepend", "replace"]
type _Position = Literal["before", "after"]

_ACTION_TYPES: Mapping[_Action, OnenotePatchActionType] = {
    "append": OnenotePatchActionType.Append,
    "insert": OnenotePatchActionType.Insert,
    "prepend": OnenotePatchActionType.Prepend,
    "replace": OnenotePatchActionType.Replace,
}

_POSITIONS: Mapping[_Position, OnenotePatchInsertPosition] = {
    "before": OnenotePatchInsertPosition.Before,
    "after": OnenotePatchInsertPosition.After,
}

_DESTRUCTIVE_ACTIONS: tuple[_Action, ...] = ("replace",)

_MAX_DESTRUCTIVE_TARGETS_NAMED = 2

_EDIT = "edit"
_DO_NOT_EDIT = "do not edit"
_NOTHING_CHANGED = "Nothing was changed."

_UNTITLED_PAGE = "an untitled page"
_UNNAMED_NOTEBOOK = "an unnamed notebook"

_DESCRIPTION = """\
Change what is already on an existing OneNote page: add content next to something, or replace \
an element outright. Pass the `page` handle from a onenote_list_pages row or a \
onenote_create_page answer, and one to twenty `commands` to run against it in order. Each \
command names a `target` (an element on the page: `body`, `title`, a `#data-id` written in the \
page's own HTML, or a generated id from onenote_read_page with `include_ids=true` — a generated \
id is passed bare with no `#` in front of it, while a `data-id` needs the `#` kept in front; \
Microsoft keeps both forms side by side on the same element rather than discarding either) and \
an `action`: `append` adds `content` as a new child of `target`, last by default or first when \
`position` is `before`; `prepend` is a shortcut for append-before, always adding `content` as \
the first child; `insert` adds `content` as a new sibling of `target`, after it by default or \
before it when `position` is `before`; `replace` throws away everything `target` held and puts \
`content` there instead. Microsoft's own schema lists a fifth action, `delete`, but its service \
refused every `delete` command this connector sent it in testing, whichever id form targeted it, \
so this tool does not offer `delete` at all — every command here takes `content`. `append` and \
`insert` accept either a `#data-id` or a generated id for `target`; `replace` needs the \
generated id for every target except `title` and an `img` or `object` inside a `div`, which \
also accept a `#data-id`. `position` only changes anything for `insert` (before or after the \
target) and for `append` on a list or the page body (first child or last child); everywhere \
else it is ignored, and Microsoft's own default is `after`. Not every element accepts every \
action: the page `body` (which is really its first div) takes `append` only; an absolutely \
positioned `div` also takes `append` only, while a `div` nested inside another `div` takes \
`replace`, `append` and `insert`; an `img` or an `object` inside a `div` takes `replace` and \
`insert` but never `append`; an `ol` or a `ul` takes `replace`, `append` and `insert`; a `table` \
takes `replace` and `insert` but never `append`; a `p`, an `li`, or a heading `h1` through `h6` \
takes `replace` and `insert` but never `append`; the page `title` takes `replace` only — use \
onenote_rename_page for that instead of spending a command here. Microsoft accepts no update at \
all against an absolutely positioned `img` or `object`, a `tr`, a `td`, `meta`, `head`, `span`, \
`a`, or a `style` tag: naming one of those as `target` is refused by Microsoft, not by this \
tool. A `replace` command erases something that was on the page, so this tool ALWAYS asks the \
person at the other end to confirm before running any command set that contains one, on top of \
asking whenever the page's notebook is shared with other people, belongs to somebody else, or \
Microsoft does not report who can see it. A command set with no `replace`, into the user's own \
unshared notebook, runs without a question. This call is NOT SAFE TO RETRY BLINDLY: Microsoft \
reports no per-command result, only one success or one failure for the whole request, and does \
not document whether an earlier command in a refused set stays applied. Any failure of this \
call, not only a timeout, can mean the set landed partly: read the page first with \
onenote_read_page, compare it against what these commands were meant to do, and send again only \
the commands that are genuinely still missing. This tool answers with the page as Microsoft's \
page index holds it right after the write. That index lags an edit, by minutes or far longer, \
so `last_modified_at` and `title` in the answer can still show the values from before this \
write while onenote_read_page already returns the change.\
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

_WRITTEN_BUT_UNREAD = (
    "The edit reached Microsoft 365 and was applied: only the read back that confirms it "
    + "failed afterward. Read the page with onenote_read_page to see what changed. Sending "
    + "these same commands to onenote_edit_page again would apply them a second time, so do "
    + "not retry it for this reason alone."
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
            + "with no `#` in front. Microsoft keeps both forms side by side on the same "
            + "element rather than discarding either. `append` and `insert` accept either "
            + "form; `replace` needs the generated id for every target except `title` and an "
            + "`img` or `object` inside a `div`, which also accept a `#data-id`."
        ),
    )
    action: _Action = Field(
        description=(
            "What to do at `target`: `append` adds `content` as a new child of `target`, last "
            + "by default or first when `position` is `before`; `prepend` is a shortcut for "
            + "append-before; `insert` adds `content` as a new sibling of `target`; `replace` "
            + "throws away what `target` held and puts `content` there instead. Not every "
            + "element accepts every action — this tool's own description carries the full "
            + "table."
        ),
    )
    position: _Position | None = Field(
        default=None,
        description=(
            "Where to put `content` relative to `target`: for `insert`, before or after the "
            + "target; for `append` on a list or the page body, first child or last child. "
            + "Microsoft's own default is `after`. Ignored by every other action."
        ),
    )
    content: str = Field(
        max_length=MAX_CONTENT_CHARACTERS,
        description=(
            "The well-formed HTML to add, or to replace `target` with. Escape `&`, `<` and `>` "
            + "where they must read as themselves rather than as markup."
        ),
    )


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
    summary: PageSummary | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors(TOOL_NAME):
        pre_read = await page_for_a_question(client, handle.page_id)
        if answer_pending or pre_read.audience.reaches_others or destructive:
            with not_graph():
                answer = await confirm(
                    _question(pre_read.page, pre_read.audience, commands, destructive=destructive),
                    about,
                )
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with graph_step(STEP_EDIT_CONTENT):
                await _edit(client, handle, commands)
            try:
                summary = await page_summary(client, handle.page_id)
            except GraphFailure as failure:
                raise ToolError(_WRITTEN_BUT_UNREAD) from failure

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert summary is not None, "a write neither asked about nor refused wrote nothing"
    return summary


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
    count = "1 command" if len(commands) == 1 else f"{len(commands)} commands"
    if destructive:
        summary = _destructive_summary(commands)
        warning = " A replace cannot be undone."
    else:
        first = commands[0]
        opening = f" with text opening {body_opening(first.content)!r}" if first.content else ""
        summary = f"the first {first.action}s {first.target!r}{opening}"
        warning = ""
    return (
        f"Change the page {title!r} in the notebook {name!r}{reason}? {count}; {summary}." + warning
    )


def _destructive_summary(commands: list[EditCommand]) -> str:
    targets = [command.target for command in commands if command.action in _DESTRUCTIVE_ACTIONS]
    named = targets[:_MAX_DESTRUCTIVE_TARGETS_NAMED]
    quoted = ", ".join(repr(target) for target in named)
    more = len(targets) - len(named)
    tail = f" and {more} more" if more else ""
    verb = "replaces" if len(targets) == 1 else "replace"
    return f"{len(targets)} of them {verb} {quoted}{tail}"


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(
        ctx, agree=_EDIT, decline=_DO_NOT_EDIT, nothing_happened=_NOTHING_CHANGED
    )


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
                    + "as its own Graph PATCH command inside the same request. Microsoft "
                    + "reports no per-command result, only one success or one failure for the "
                    + "whole set, and does not document whether an earlier command stays "
                    + "applied after a later one is refused: treat any failure as a set that "
                    + "may be partly applied, and see this tool's own description for how to "
                    + "recover before sending a changed set again."
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
