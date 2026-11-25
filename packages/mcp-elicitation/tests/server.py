"""A server whose tools ask the way a real MCP's would, and record what they did."""

from collections.abc import Awaitable
from collections.abc import Callable
from typing import Literal
from typing import cast

from fastmcp import Context
from fastmcp import FastMCP
from fastmcp.client.client import CallToolResult
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.memory import MemoryStore
from mcp.types import ElicitRequestFormParams
from mcp.types import ElicitResult
from mcp.types import InputRequiredResult
from mcp_configs import ElicitationSettings

from mcp_elicitation import ASKS_CONFIRMATION
from mcp_elicitation import Elicitation
from mcp_elicitation import NeedsChoice
from mcp_elicitation import NotConfirmed
from mcp_elicitation import Option
from mcp_elicitation import create_request_state_security
from mcp_elicitation import needs_answer

ERAS = ["legacy", "auto"]
"""`legacy` speaks 2025-11-25 (the tool waits); `auto` speaks 2026-07-28 (the tool is re-run)."""

FOLDERS = [
    Option(ref="f1", label="Inbox/XYZ (822 mails)"),
    Option(ref="f2", label="Archive/XYZ (3 mails)"),
    Option(ref="f3", label="Shared/XYZ (40 mails)"),
]

type Era = Literal["legacy", "auto"]
type Content = dict[str, str | int | float | bool | list[str] | None]
type Handler = Callable[[str, object, ElicitRequestFormParams, object], Awaitable[ElicitResult]]


class Mailbox:
    """What the tools change, so a test can tell whether one went ahead."""

    def __init__(self) -> None:
        self.rule_name: str = "Newsletters"
        self.deleted: list[str] = []


def build_server(
    mailbox: Mailbox,
    *,
    settings: ElicitationSettings | None = None,
    store: AsyncKeyValue | None = None,
) -> FastMCP:
    settings = settings or ElicitationSettings()
    elicitation = Elicitation(settings, store or MemoryStore())
    mcp = FastMCP("mailbox", request_state_security=create_request_state_security(settings))

    @mcp.tool(meta=ASKS_CONFIRMATION)
    async def delete_rule(ctx: Context) -> str | InputRequiredResult:
        answer = await elicitation.confirm(
            ctx,
            f'Delete the inbox rule "{mailbox.rule_name}"?',
            agree="Delete the rule",
            decline="Keep the rule",
            nothing_happened="The rule was not deleted.",
        )
        if needs_answer(answer):
            return answer
        mailbox.deleted.append(mailbox.rule_name)
        return f"deleted, skipped={answer.skipped}"

    @mcp.tool(meta=ASKS_CONFIRMATION)
    async def delete_rule_softly(ctx: Context) -> str | InputRequiredResult:
        answer = await elicitation.confirm(
            ctx,
            f'Delete the inbox rule "{mailbox.rule_name}"?',
            agree="Delete the rule",
            decline="Keep the rule",
            nothing_happened="The rule was not deleted.",
            raises=False,
        )
        if needs_answer(answer):
            return answer
        if isinstance(answer, NotConfirmed):
            return f"refused: {answer.reason}"
        mailbox.deleted.append(mailbox.rule_name)
        return "deleted"

    @mcp.tool(meta=ASKS_CONFIRMATION)
    async def empty_folder(ctx: Context) -> str | NeedsChoice | InputRequiredResult:
        picked = await elicitation.choose_one(ctx, "Delete all mails in which folder?", FOLDERS)
        if needs_answer(picked):
            return picked
        mailbox.deleted.append(picked.ref)
        return f"emptied {picked.ref}"

    @mcp.tool(meta=ASKS_CONFIRMATION)
    async def empty_folders(ctx: Context) -> str | NeedsChoice | InputRequiredResult:
        picked = await elicitation.choose_many(
            ctx, "Delete all mails in which folders?", FOLDERS, min_items=2, max_items=2
        )
        if needs_answer(picked):
            return picked
        mailbox.deleted.extend(picked.refs)
        return f"emptied {','.join(picked.refs)}"

    @mcp.tool(meta=ASKS_CONFIRMATION)
    async def pick_then_confirm(ctx: Context) -> str | NeedsChoice | InputRequiredResult:
        picked = await elicitation.choose_one(ctx, "Which folder?", FOLDERS)
        if needs_answer(picked):
            return picked
        answer = await elicitation.confirm(
            ctx,
            f"Delete all mails in {picked.ref}?",
            agree="Delete the mails",
            decline="Keep them",
            nothing_happened="No mail was deleted.",
        )
        if needs_answer(answer):
            return answer
        mailbox.deleted.append(picked.ref)
        return f"emptied {picked.ref}"

    return mcp


def answering(*contents: Content | ElicitResult) -> tuple[Handler, list[ElicitRequestFormParams]]:
    """A client that gives these answers in order, and the forms it was shown."""
    shown: list[ElicitRequestFormParams] = []
    remaining = list(contents)

    async def handler(
        _message: str, _response_type: object, params: ElicitRequestFormParams, _context: object
    ) -> ElicitResult:
        shown.append(params)
        answer = remaining.pop(0)
        if isinstance(answer, ElicitResult):
            return answer
        return ElicitResult(action="accept", content=answer)

    return handler, shown


def returned(result: CallToolResult) -> object:
    """What the tool returned. A tool that may return text and a model wraps it in `result`."""
    assert result.structured_content is not None
    return cast("object", result.structured_content["result"])


def form_field(params: ElicitRequestFormParams, name: str) -> dict[str, object]:
    properties = cast("dict[str, dict[str, object]]", params.requested_schema["properties"])
    return properties[name]
