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
Adds content next to an element on one page, or replaces an element. One to twenty `commands` run \
in order. There is no `delete` action. onenote_rename_page is the sibling for the title. OneNote \
can show the change to everyone who opens the notebook.

Notes:
- A `replace` erases content, so this tool always asks the user to agree for a set that contains \
one. For other sets, it asks before it writes into a notebook that is shared with other people or \
belongs to somebody else. A set in the user's own unshared notebook runs without a question.
- Microsoft reports one result for the whole set. A failure can mean a partly applied set: read \
the page with onenote_read_page and resend only the missing commands.
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
            "The element to change: `body` (the page's first div), `title`, a `#data-id` the "
            + "author wrote with the `#` kept, or a generated id. Read the page with "
            + "`include_ids=true` to get one, with no `#` in front. Microsoft keeps both forms "
            + "on the element. `append` and `insert` accept either form. `replace` needs the "
            + "generated id, except `title`, and an `img` or `object` inside a `div`, which "
            + "also accept a `#data-id`. `body` and an absolutely positioned `div` accept only "
            + "`append`."
        ),
    )
    action: _Action = Field(
        description=(
            "`append` adds `content` as the last child, or first when `position` is `before`. "
            + "`prepend` is `append` as the first child. `insert` adds `content` as a sibling "
            + "after `target`, or before it when `position` is `before`. `replace` erases what "
            + "`target` held and puts `content` there. A nested `div`, `ol`, and `ul` accept "
            + "`replace`, `append`, and `insert`. An `img` or `object` inside a `div`, a "
            + "`table`, a `p`, an `li`, and `h1` to `h6` accept `replace` and `insert`. "
            + "`title` accepts only `replace`. Microsoft refuses `tr`, `td`, `meta`, `head`, "
            + "`span`, `a`, `style`, and an absolutely positioned `img` or `object`."
        ),
    )
    position: _Position | None = Field(
        default=None,
        description=(
            "Where `content` goes next to `target`. For `insert`, before or after `target`. "
            + "For `append` on a list or the page body, first child or last child. Microsoft's "
            + "default is `after`. Every other action ignores it."
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
                    "The page to change: the `uri` of a onenote_list_pages row or a "
                    + "onenote_create_page answer, copied word for word. The shape is "
                    + "onenote:///pages/{id}. A section handle is not a page handle."
                ),
            ),
        ],
        commands: Annotated[
            list[EditCommand],
            Field(
                min_length=1,
                max_length=MAX_COMMANDS,
                description=(
                    "One to twenty changes to run against the page, in order. Each command "
                    + "runs as its own `PATCH` command inside one request."
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
