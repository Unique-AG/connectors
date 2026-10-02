from collections.abc import Mapping
from contextlib import suppress
from typing import Annotated, Literal

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import InputRequiredResult
from msgraph.generated.models.message_rule import MessageRule
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import GraphNotFound, graph_errors, graph_step, not_graph
from office_365_mcp.shared.handles import MailRuleHandle, mail_rule_handle
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.rules import (
    READ_ONLY_RULE,
    RuleActions,
    RuleConditions,
    actions_of,
    conditions_of,
    read_rule,
    rule_confirmation_id,
    rule_of,
)
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE_IDEMPOTENT,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "outlook_delete_mail_rule"

STEP_DELETE = "delete_mail_rule"

GRAPH_PERMISSIONS: tuple[str, ...] = ("MailboxSettings.ReadWrite",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "rule_ref": "outlook:///rules/AQAAAJSYNTHETIC-rule-one",
}

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return the rule that this call named, and nothing was deleted. The "
    + "handle is well formed. A person or an earlier call of this tool probably deleted the rule. "
    + "Call outlook_get_mailbox_settings again. If the rule is not in that result, it is already "
    + "gone and nothing is left to delete. If you call this tool again with the same arguments, "
    + "the call will fail the same way."
)

_AGREE = "delete the rule"
_DECLINE = "keep the rule"
_NOTHING_DELETED = "The rule was not deleted."

_DESCRIPTION = """\
Deletes one inbox rule in the signed-in user's own mailbox. The rule then stops acting on \
incoming mail. A rule holds no mail, so no message is deleted. outlook_get_mailbox_settings lists \
the rules and their handles. outlook_disable_mail_rule turns a rule off and keeps it.

Notes:
- This tool always asks the user to agree, and the question names the rule. This connector \
cannot restore a deleted rule.
- This tool refuses a read-only rule.
- This call is safe to repeat after a timeout. A second call finds no rule and reports that.
"""

_NOT_A_RULE_HANDLE = (
    "outlook_delete_mail_rule takes a rule handle in `rule_ref`: outlook:///rules/{id}, exactly "
    + "as outlook_get_mailbox_settings reported it in `uri`. The name of a rule is not a handle. "
    + "A message handle and a folder handle are not rule handles. Nothing was deleted. If you "
    + "call this tool again with the same arguments, the call will fail the same way."
)


class DeletedRule(BaseModel):
    uri: str = Field(
        description=(
            "The handle that this call was given, echoed back. The rule that this handle named is "
            + "deleted, so do not pass this handle to another tool."
        )
    )
    display_name: str | None = Field(
        description=(
            "The name of the rule, as Microsoft 365 reported it immediately before the delete. The "
            + "value is null when Microsoft 365 reported no name."
        )
    )
    conditions: RuleConditions | None = Field(
        description=(
            "The conditions that the rule had immediately before the delete. Only the predicates "
            + "that the rule set appear. Null when Graph reported no condition."
        )
    )
    exceptions: RuleConditions | None = Field(
        description=(
            "The exception conditions that the rule had immediately before the delete, in the "
            + "same shape as `conditions`. Null when Graph reported no exception."
        )
    )
    actions: RuleActions | None = Field(
        description=(
            "The actions that the rule took on each matching message immediately before the "
            + "delete. Only the actions that the rule set appear. Null when Graph reported none."
        )
    )
    deleted: Literal[True] = Field(
        description=(
            "Always true, because this tool answers only when the rule is gone. It is also true "
            + "when Graph found no rule to delete after this call read the rule."
        )
    )


async def delete_mail_rule(
    client: GraphServiceClient, *, rule_ref: str, confirm: Confirm
) -> DeletedRule | InputRequiredResult:
    handle = mail_rule_handle(rule_ref)
    if handle is None:
        raise ToolError(_NOT_A_RULE_HANDLE)

    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors(TOOL_NAME):
        rule = await read_rule(client, handle)
        if rule.is_read_only:
            refused = f"{_NOTHING_DELETED} {READ_ONLY_RULE}"
        if refused is None:
            with not_graph():
                answer = await confirm(
                    _question(handle, rule), rule_confirmation_id(TOOL_NAME, handle.uri)
                )
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with suppress(GraphNotFound), graph_step(STEP_DELETE):
                await rule_of(client, handle).delete()

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    return DeletedRule(
        uri=handle.uri,
        display_name=rule.display_name,
        conditions=conditions_of(rule.conditions),
        exceptions=conditions_of(rule.exceptions),
        actions=actions_of(rule.actions),
        deleted=True,
    )


def _question(handle: MailRuleHandle, rule: MessageRule) -> str:
    named = cut_for_a_question(rule.display_name or handle.uri)
    return (
        f"Delete the inbox rule {named!r}? The rule then stops acting on incoming mail. No "
        + "message is deleted. This connector cannot restore a deleted rule."
    )


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_AGREE, decline=_DECLINE, nothing_happened=_NOTHING_DELETED)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Delete a Mail Rule",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE_IDEMPOTENT,
    )
    async def outlook_delete_mail_rule(
        rule_ref: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The rule to delete, as the `uri` of a rule that outlook_get_mailbox_settings "
                    + "reports, copied word for word. The shape is outlook:///rules/{id}. The name "
                    + "of a rule is not a handle."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> DeletedRule | InputRequiredResult:
        return await delete_mail_rule(client, rule_ref=rule_ref, confirm=a_person_agrees(ctx))
