"""`outlook_disable_mail_rule` turns one existing inbox rule off, and does nothing else.

**Enabling is the attack. Disabling is the story.** An inbox rule that forwards or redirects
mail sends copies out of the organization. This deployment has no `Mail.Send` permission
anywhere, and it creates no draft for anyone to notice. `MailboxSettings.ReadWrite` is the only
permission it needs. As a result, this tool must not act on an instruction such as "restore my
old partner-forwarding rule". A mail body or a document that this connector read can carry that
instruction. The `enabled` field has the type `Literal[False]`. This makes it impossible to
represent a request to re-arm an existing forwarding rule in the schema, rather than refuse it
only at runtime. No argument can carry the other value.

**This tool cannot create a rule, for the same reason. Microsoft's own example shows why.** The
worked example on the create endpoint is a rule with two actions: `forwardTo` an address, and
`stopProcessingRules: true`. It copies mail to an outside address, and it hides itself from
every rule that runs after it
(https://learn.microsoft.com/en-us/graph/api/mailfolder-post-messagerules). A model that uses
that tool can copy the same shape. This connector registers no tool that creates one.

**This tool reads the rule before it writes it. As a result, the transcript records what was
turned off.** A rule's display name is a label its author chose, not a description. A rule
called `Newsletters` can forward mail out of the organization. As a result, the answer states
what the rule actually did. It names the addresses the rule forwarded, redirected, or attached
mail to, the folder it moved mail to, and whether it deleted mail. In Outlook, the user can undo
this disable action in one click. A user who cannot see what was disabled cannot tell whether
the undo matters.

**This tool refuses a rule that Microsoft Graph marks `isReadOnly`, before the write.** Microsoft
documents the flag as a rule that "cannot be modified or deleted by the rules REST API"
(https://learn.microsoft.com/en-us/graph/api/messagerule-update). As a result, the PATCH request
fails. This refusal names which rule, and why, instead of returning a Graph error about an id.

**`no_retry()` on the PATCH.** The SDK retries every verb on responses 429, 503, and 504.
`GRAPH_MAX_RETRIES` defaults to 3. Disabling the rule twice is harmless. Getting a response that
does not match what was actually applied is not harmless: this tool's answer states what the
mailbox now holds.

**This tool takes no `mailbox` argument.** Microsoft Graph publishes no `.Shared` variant of
`MailboxSettings.ReadWrite`. As a result, this tool cannot reach a shared mailbox's rules.
"""

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

# This is Graph's locale-independent well-known name for the Inbox. It reaches the Inbox in a
# mailbox of any language. Graph attaches `messageRules` to `mailFolder`, but documents the
# collection as the rules that apply to the Inbox. So this is a fixed address, not a folder
# handle that a caller passes in.
_INBOX_FOLDER = "inbox"

# Everything the answer reads. `conditions` and `exceptions` are absent on purpose: this reports
# what the rule did. A partial reading of which mail it acted on would look like an answer to a
# question nobody asked.
_RULE_FIELDS: tuple[str, ...] = (
    "id",
    "displayName",
    "isEnabled",
    "isReadOnly",
    "actions",
)

# This is bound with `=`, not aliased with `type`: it serves as both the query parameters'
# constructor and `RequestConfiguration`'s argument, and a `TypeAliasType` is not callable.
_RuleQuery = MessageRuleItemRequestBuilder.MessageRuleItemRequestBuilderGetQueryParameters

_DESCRIPTION = """\
This tool turns one existing inbox rule of the signed-in user's mailbox off, at once and on \
every device. Use it for "stop that rule forwarding my mail" or "why does my mail get filed, \
turn that off".

Notes:
- This tool can only disable a rule. `enabled` accepts only the value false, so this tool \
cannot enable a rule or create one. To re-enable a rule, the user clicks once in Outlook \
(Settings, Mail, Rules).
- `rule_ref` is the `uri` of a rule, as outlook_get_mailbox_settings reports it. No other tool \
mints one.
- This tool refuses a rule that Microsoft Graph marks read-only, because this API cannot change \
it.
"""

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
    """One rule, as it stood when it was read, and as Microsoft 365 answered the write.

    This model names what the rule *does* field by field, rather than handing over Graph's
    `actions` object. A model given that object has to infer "this sends copies of my mail out
    of the organization" from a list of recipients under a key it must already know to look for.
    """

    uri: str = Field(
        description=(
            "The handle this answer is about, exactly as the request passed it. A later "
            + "answer can then refer to the same rule."
        )
    )
    display_name: str | None = Field(
        description=(
            "The rule's name, chosen by whoever created it. It is a label, not a description: "
            + "a rule called `Newsletters` can forward mail out of the organization. Read the "
            + "action fields below instead. This field is null when Microsoft Graph recorded "
            + "no name."
        )
    )
    was_enabled: bool | None = Field(
        description=(
            "Whether the rule was active before this call, read when this tool fetched it. "
            + "This field is null when Microsoft Graph did not say. False means that the rule "
            + "was already off, and this call changed nothing. This tool states that fact, "
            + "rather than reporting a change that did not happen."
        )
    )
    is_enabled: bool | None = Field(
        description=(
            "Whether Microsoft 365 now reports the rule as running, read off its own response "
            + "to the write, not from the argument. This field is null when Microsoft Graph "
            + "returned no rule to read it from. Any value other than false here means that "
            + "Microsoft 365 disagrees that this call disabled the rule."
        )
    )
    forwarded_to: list[str] = Field(
        description=(
            "Addresses this rule forwarded a copy of each matching message to. An empty list "
            + "means this rule forwarded nothing. Each entry is the SMTP address Microsoft "
            + "Graph recorded, or the display name when it recorded no address. An address "
            + "outside the user's own domain means that copies of their mail already left the "
            + "organization automatically, even though the rule is now off."
        )
    )
    redirected_to: list[str] = Field(
        description=(
            "Addresses this rule redirected each matching message to. A redirect passes the "
            + "message on with the original sender kept, so replies go to whoever wrote it, "
            + "not to this user. It is harder to notice than a forward, but it is not less "
            + "serious."
        )
    )
    forwarded_as_attachment_to: list[str] = Field(
        description=(
            "Addresses this rule forwarded each matching message to as an attachment. The "
            + "whole original message travels, headers included. Read this field the same way "
            + "as `forwarded_to`."
        )
    )
    moved_to_folder: str | None = Field(
        description=(
            "The Graph id of the folder this rule moved matching mail to. This field is null "
            + "when the rule moved nothing. The id is opaque on its own: "
            + "outlook_browse_folders reports the id and the name together, to turn this into "
            + "a folder name."
        )
    )
    deleted: bool | None = Field(
        description=(
            "True when the rule deleted matching messages, by either of two actions: "
            + "Microsoft's `delete`, which moves them to Deleted Items, where the user can "
            + "still find them, or `permanentDelete`, which does not. This field does not "
            + "tell the two apart. It is null when Microsoft Graph reported neither."
        )
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
    """The rule that `rule_ref` names. This function reads it, switches it off, and reports what
    it did."""
    handle = mail_rule_handle(rule_ref)
    if handle is None:
        raise ToolError(_NOT_A_RULE_HANDLE)

    with graph_errors(TOOL_NAME):
        before = await _read_rule(client, handle)
        # This function decides inside the `with` block, and raises outside it. `graph_errors`
        # treats a `ToolError` that escapes it as a Graph call that this seam cannot classify.
        # The read above already succeeded.
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
    """The one property this tool writes. kiota omits a property that was never set. As a result,
    the body on the wire holds `isEnabled` alone, and no action, condition, or name of this rule
    can be touched through it. The absent arguments are the control, not a filter placed
    somewhere downstream."""
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
    """Where the rule sent mail, one entry per recipient.

    The display name stands in when Microsoft Graph recorded no address, rather than the
    recipient being dropped. A destination that this answer leaves out is a destination the
    user does not know about.
    """
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
    """Whether the rule destroyed the message, by either of Graph's two spellings. This function
    folds the two together, because both answer "does this rule delete my mail" with yes."""
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
                    + "on each rule. Call that tool with include=rules to list the mailbox's "
                    + "rules and their handles. This tool accepts one rule per call. There is "
                    + "no batch."
                )
            ),
        ],
        enabled: Annotated[
            Literal[False],
            Field(
                description=(
                    "This value is always false. This field is written out, rather than "
                    + "assumed, so that a call reads as what it does."
                )
            ),
        ],
        client: GraphServiceClient = graph,
    ) -> DisabledRule:
        # The schema reads `enabled`, not this function body: `Literal[False]` is what makes
        # enabling impossible to represent, so there is nothing left here to branch on.
        assert enabled is False, "the schema admits no other value"
        return await disable_mail_rule(client, rule_ref=rule_ref)
