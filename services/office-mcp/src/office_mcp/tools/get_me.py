"""`get_me` — the signed-in Microsoft 365 user's own profile.

The tool a model calls first, and the one every other answer is correlated against: "my chats",
"messages from me", "did I organise this meeting" all resolve to an identity that a token carries
and a model cannot see. One cheap request, and its answer is stable for the session.

The name is `get_me` and not `whoami`. This is the first name on the surface and every name after it
is `verb_noun`, so the shell idiom would have made the odd tool out of the very tool a model reaches
for first — and a name is the one thing about a tool that cannot be corrected quietly later, because
every caller that learned it has to learn it again. (Microsoft's own M365 connector arrived at
`get_me` independently, which is one less name for a model to have to learn twice.)

**The trap this tool exists to teach is that its three identifiers are not interchangeable.**
`email` is Graph's `mail`, the canonical primary SMTP address, and it is null for guest and
unlicensed accounts. `user_principal_name` looks like an address and is not guaranteed to be one —
a tenant may issue it on a different domain — so matching message addresses against it can silently
return nothing. `user_id` is the immutable directory object id and the only value safe to compare
against another tool's `user_id`. The description says all three, because a model that guesses
wrong here gets an empty answer rather than an error.

The Graph call itself is `shared/identity.py` rather than this file's own, though this is its only
caller today: "who am I" is the fact every other answer on this connector gets correlated against,
and the next tool to want it wants one id off the same call rather than a profile — two `GET /me`
calls under two projections would be two answers to one question. What is this tool's own is
everything a caller sees — the name, the description above, the permission it declares, and
`SignedInUser` below, which is the shape and the wording of the answer.
"""

import httpx
from fastmcp import FastMCP
from msgraph.generated.models.user import User
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_mcp.graph_client import graph_client_for
from office_mcp.shared import identity
from office_mcp.shared.seam import READ_ONLY, graph_token, graph_tool_errors

TOOL_NAME = "get_me"

# The delegated Graph permissions this tool calls under. The registry unions every tool's, which is
# what sign-in asks Entra to consent to, and a refusal is worded from this same tuple — so a tool
# file that names its permissions here cannot be registered without them reaching the consent
# screen, and cannot report a 403 naming a permission it does not use.
GRAPH_PERMISSIONS: tuple[str, ...] = (identity.GRAPH_PERMISSION,)

# Built once at import: a call inside a parameter default rebuilds the descriptor on every
# registration and is a lint error in both of this repo's checkers.
_TOKEN: str = graph_token(*GRAPH_PERMISSIONS)

_DESCRIPTION = """\
Return the signed-in Microsoft 365 user's own profile: `user_id`, `display_name`, `email`, \
`user_principal_name` and `job_title`.

Call this before anything that turns on who "I", "me" or "my" is: addressing the signed-in user by \
name, or deciding whether a person named somewhere else is them. It is one cheap request and its \
answer is stable for the session.

`email` is the canonical primary SMTP address (Microsoft's `mail`) and the right value to match a \
sender or recipient against — but it is null for guest and unlicensed accounts, and \
`user_principal_name` (Microsoft's `userPrincipalName`) is then the best available identifier. Do \
not treat the two as interchangeable when both are present: a tenant can issue a \
user_principal_name on a different domain from the email address, so matching addresses against it \
can silently return nothing. Compare `user_id` — the immutable directory object id — against \
another `user_id`, never against a name; compare `email` against an address.\
"""


class SignedInUser(BaseModel):
    """The signed-in user's own profile, as the MCP client sees it.

    Field names are snake_case here and in every other tool payload, which is the one place this
    connector deliberately does not echo Graph's spelling — the field descriptions name the Graph
    property wherever the two differ. Two of them differ by more than case, so that one thing has
    one name across this server's whole surface: a person's Entra object id is `user_id` and an
    email address is `email`, here and on every payload that follows. Graph calls them `id` and
    `mail`, and this is the payload the others will be read against.
    """

    user_id: str = Field(
        description=(
            "The user's immutable Microsoft Entra object id (Graph `id`). The only identifier safe "
            + "to compare against another `user_id` this connector reports; names and addresses "
            + "change."
        )
    )
    display_name: str | None = Field(
        description="The user's name as Microsoft 365 shows it. Null only on incomplete accounts."
    )
    email: str | None = Field(
        description=(
            "The canonical primary SMTP address (Graph `mail`), and the right thing to match a "
            + "sender or recipient address against. Null for guest and unlicensed accounts — "
            + "fall back to user_principal_name."
        )
    )
    user_principal_name: str | None = Field(
        description=(
            "The sign-in name (Graph `userPrincipalName`). Usually looks like an email address "
            + "but is not guaranteed to be one: a tenant may issue it on a different domain than "
            + "`email`, so treat it as an identifier rather than an address unless `email` is null."
        )
    )
    job_title: str | None = Field(
        description="The user's job title, when the directory records one."
    )


async def get_signed_in_user(client: GraphServiceClient) -> SignedInUser:
    """The caller's profile, projected onto the five properties this tool promises."""
    return _profile(await identity.signed_in_user(client))


def _profile(user: User) -> SignedInUser:
    """Graph's `user` as this tool answers, renaming the two properties that differ by more."""
    assert user.id is not None, "Graph answered GET /me with a user that has no id"
    return SignedInUser(
        user_id=user.id,
        display_name=user.display_name,
        email=user.mail,
        user_principal_name=user.user_principal_name,
        job_title=user.job_title,
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    """Declare this tool against the shared Graph transport.

    `transport` is the long-lived `httpx.AsyncClient` from `create_graph_transport`; the tool
    borrows it per call and never owns it. `create_app` closes it on shutdown.
    """

    @mcp.tool(
        name=TOOL_NAME,
        title="Get My Profile",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def get_me(graph_token: str = _TOKEN) -> SignedInUser:
        with graph_tool_errors(*GRAPH_PERMISSIONS):
            return await get_signed_in_user(graph_client_for(transport, graph_token))
