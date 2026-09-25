from collections.abc import Mapping
from typing import Annotated, Literal, Self

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from msgraph.generated.models.message_rule import MessageRule
from msgraph.generated.models.message_rule_actions import MessageRuleActions
from msgraph.generated.models.recipient import Recipient
from msgraph.generated.users.item.mail_folders.item.message_rules.item.message_rule_item_request_builder import (  # noqa: E501
    MessageRuleItemRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry
from office_365_mcp.shared.handles import MailRuleHandle, mail_rule_handle
from office_365_mcp.shared.seam import WRITE_IDEMPOTENT, graph_client_for_caller

TOOL_NAME = "outlook_disable_mail_rule"

STEP_READ = "read_mail_rule"
STEP_DISABLE = "disable_mail_rule"

GRAPH_PERMISSIONS: tuple[str, ...] = ("MailboxSettings.ReadWrite",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "rule_ref": "outlook:///rules/AQAAAJSYNTHETIC-rule-one",
    "enabled": False,
}

_INBOX_FOLDER = "inbox"

_RULE_FIELDS: tuple[str, ...] = (
    "id",
    "displayName",
    "isEnabled",
    "isReadOnly",
    "actions",
)

_RuleQuery = MessageRuleItemRequestBuilder.MessageRuleItemRequestBuilderGetQueryParameters

_DESCRIPTION = (
    "Turns one existing inbox rule off. It cannot enable a rule or create one — the user "
    "clicks once in Outlook to re-enable it — and outlook_get_mailbox_settings reports each "
    "rule's handle in `uri`."
)

_NOT_A_RULE_HANDLE = (
    "outlook_disable_mail_rule changed nothing: `rule_ref` is not a rule handle. A rule handle "
    + "has exactly one shape, outlook:///rules/{rule_id} with the id percent-encoded. "
    + "outlook_get_mailbox_settings reports one as `uri` on every rule it lists. It is the only "
    + "tool here that mints them. Copy that value rather than assembling one: a rule's display "
    + "name, a sender's address and a bare id are not handles. Neither is a message, folder or "
    + "draft handle under the same scheme, which addresses other things entirely. Call "
    + "outlook_get_mailbox_settings with include=rules to see the rules and their handles, then "
    + "call again. Retrying this value will fail identically."
)

_READ_ONLY_RULE = (
    "Microsoft 365 marks this rule read-only, so the rules API cannot change it, and nothing was "
    + "written. Microsoft applies that to rules another client or an administrator created. It "
    + "says nothing about what the rule does: a read-only rule still runs, and can still forward "
    + "mail. It can only be turned off where it was made: Outlook (Settings, Mail, Rules) for the "
    + "user's own rules, or the Exchange admin center for an administrator's. Tell the user "
    + "that, and what the rule does, instead of trying another handle. Retrying will fail "
    + "identically."
)


class DisabledRule(BaseModel):
    uri: str = Field(
        description="The handle this answer is about, exactly as the request passed it."
    )
    display_name: str | None = Field(
        description="The rule's name; a label, not a description — read the action fields instead."
    )
    was_enabled: bool | None = Field(
        description="Whether the rule was active before this call; null if Graph did not say."
    )
    is_enabled: bool | None = Field(
        description="Whether Microsoft 365 now reports the rule as running, read off its write."
    )
    forwarded_to: list[str] = Field(
        description="Addresses this rule forwarded a copy of each matching message to."
    )
    redirected_to: list[str] = Field(
        description=(
            "Addresses this rule redirected each matching message to, with the original "
            + "sender kept."
        )
    )
    forwarded_as_attachment_to: list[str] = Field(
        description="Addresses this rule forwarded each matching message to as an attachment."
    )
    moved_to_folder: str | None = Field(
        description="The Graph id of the folder this rule moved matching mail to; null if none."
    )
    deleted: bool | None = Field(
        description="True when the rule deleted matching messages, by either delete action."
    )

    @classmethod
    def from_rule(
        cls, handle: MailRuleHandle, *, before: MessageRule, after: MessageRule | None
    ) -> Self:
        actions = before.actions
        return cls(
            uri=handle.uri,
            display_name=before.display_name,
            was_enabled=before.is_enabled,
            is_enabled=None if after is None else after.is_enabled,
            forwarded_to=_addresses(None if actions is None else actions.forward_to),
            redirected_to=_addresses(None if actions is None else actions.redirect_to),
            forwarded_as_attachment_to=_addresses(
                None if actions is None else actions.forward_as_attachment_to
            ),
            moved_to_folder=None if actions is None else actions.move_to_folder,
            deleted=_deletes(actions),
        )


async def disable_mail_rule(client: GraphServiceClient, *, rule_ref: str) -> DisabledRule:
    handle = mail_rule_handle(rule_ref)
    if handle is None:
        raise ToolError(_NOT_A_RULE_HANDLE)

    with graph_errors(TOOL_NAME):
        before = await _read_rule(client, handle)
        after = None if before.is_read_only else await _disable_rule(client, handle)

    if before.is_read_only:
        raise ToolError(_READ_ONLY_RULE)

    return DisabledRule.from_rule(handle, before=before, after=after)


async def _read_rule(client: GraphServiceClient, handle: MailRuleHandle) -> MessageRule:
    with graph_step(STEP_READ):
        rule = await _rule_of(client, handle).get(
            request_configuration=RequestConfiguration[_RuleQuery](
                query_parameters=_RuleQuery(select=list(_RULE_FIELDS))
            )
        )
    assert rule is not None, "Graph answered a rule read with no rule and no error"
    return rule


async def _disable_rule(client: GraphServiceClient, handle: MailRuleHandle) -> MessageRule | None:
    with graph_step(STEP_DISABLE):
        return await _rule_of(client, handle).patch(
            MessageRule(is_enabled=False),
            request_configuration=RequestConfiguration[QueryParameters](options=no_retry()),
        )


def _rule_of(client: GraphServiceClient, handle: MailRuleHandle) -> MessageRuleItemRequestBuilder:
    return client.me.mail_folders.by_mail_folder_id(_INBOX_FOLDER).message_rules.by_message_rule_id(
        handle.rule_id
    )


def _addresses(recipients: list[Recipient] | None) -> list[str]:
    named: list[str] = []
    for recipient in recipients or []:
        email = recipient.email_address
        if email is None:
            continue
        address = email.address if email.address else email.name
        if address is not None:
            named.append(address)
    return named


def _deletes(actions: MessageRuleActions | None) -> bool | None:
    if actions is None:
        return None
    said = [flag for flag in (actions.delete, actions.permanent_delete) if flag is not None]
    return any(said) if said else None


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Disable Mail Rule",
        description=_DESCRIPTION,
        annotations=WRITE_IDEMPOTENT,
    )
    async def outlook_disable_mail_rule(
        rule_ref: Annotated[
            str,
            Field(
                description=(
                    "The rule to turn off: the `uri` that outlook_get_mailbox_settings reports "
                    + "on each rule."
                )
            ),
        ],
        enabled: Annotated[
            Literal[False],
            Field(description="Always `false`; disabling is the only action this tool can take."),
        ],
        client: GraphServiceClient = graph,
    ) -> DisabledRule:
        assert enabled is False, "the schema admits no other value"
        return await disable_mail_rule(client, rule_ref=rule_ref)
