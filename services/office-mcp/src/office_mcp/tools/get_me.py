"""`get_me` — return the signed-in user's own profile.

The name is `get_me`, not the shell idiom `whoami`, to keep the verb_noun pattern every tool
name follows. A tool name cannot change later: every caller that learned it must learn it
again. Microsoft's own M365 connector uses the same name.

**Trap:** `email`, `user_principal_name`, and `user_id` are not interchangeable. Use email to match
sender and recipient addresses. Use user_principal_name only when email is null (guest or unlicensed
accounts). Compare user_id only against another user_id—it is the immutable Entra object id.
"""

import httpx
from fastmcp import FastMCP
from msgraph.generated.models.user import User
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_mcp.graph_client import graph_errors
from office_mcp.shared import identity
from office_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "get_me"

GRAPH_PERMISSIONS: tuple[str, ...] = (identity.GRAPH_PERMISSION,)

_DESCRIPTION = """\
Return the signed-in user's profile: user_id, display_name, email, user_principal_name, job_title.

Call this tool before any action that depends on who "I", "me", or "my" refers to. The answer is \
stable for the session.

Trap: email and user_principal_name are not the same value. Use email to match sender or recipient \
addresses. Use user_principal_name only when email is null (guest or unlicensed accounts). \
Compare user_id with another user_id only—it is the immutable Entra object id.\
"""


class SignedInUser(BaseModel):
    """The signed-in user's profile.

    Field names are snake_case; see field descriptions for Graph names.
    """

    user_id: str = Field(
        description=(
            "The user's immutable Entra object id (Graph id). Compare only against another "
            + "user_id."
        )
    )
    display_name: str | None = Field(
        description="The user's name as Microsoft 365 shows it. Null only on incomplete accounts."
    )
    email: str | None = Field(
        description=(
            "The canonical primary SMTP address (Graph mail). Null for guest and unlicensed "
            + "accounts. Use user_principal_name when null."
        )
    )
    user_principal_name: str | None = Field(
        description=(
            "The sign-in name (Graph userPrincipalName). Usually looks like an email address "
            + "but may be on a different domain. Use only when email is null."
        )
    )
    job_title: str | None = Field(
        description="The user's job title from the directory, when the directory records one."
    )


async def get_signed_in_user(client: GraphServiceClient) -> SignedInUser:
    """Return the caller's profile with the five properties this tool promises.

    The `graph_errors` block here does nothing about failures — `shared/identity.py` opens its own
    and classifies them — and everything about naming them: `operation` is the tool's own name, and
    a tool file is the only thing that knows it. Every other tool opens its named block at its own
    Graph call; this one's Graph call is in `shared/`, so the block comes out one level up rather
    than the name going one level down.
    """
    with graph_errors(TOOL_NAME):
        return _profile(await identity.signed_in_user(client))


def _profile(user: User) -> SignedInUser:
    """Map Graph user to SignedInUser, renaming id→user_id and mail→email."""
    assert user.id is not None, "Graph answered GET /me with a user that has no id"
    return SignedInUser(
        user_id=user.id,
        display_name=user.display_name,
        email=user.mail,
        user_principal_name=user.user_principal_name,
        job_title=user.job_title,
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    """Register this tool with the shared Graph transport.

    The tool borrows the transport per call.
    """
    # Here rather than at module level, because this is where `transport` is: the dependency closes
    # over it, and a default is evaluated when the `def` below runs, which is inside this call. A
    # name in the default rather than the call itself — a call there is ruff's B008.
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Get My Profile",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def get_me(client: GraphServiceClient = graph) -> SignedInUser:
        return await get_signed_in_user(client)
