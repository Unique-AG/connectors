"""`get_me` — the signed-in user's own profile. A tool name cannot change once callers learn it."""

from collections.abc import Mapping
from typing import Self

import httpx
from fastmcp import FastMCP
from msgraph.generated.models.user import User
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors
from office_365_mcp.shared import identity
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "get_me"

GRAPH_PERMISSIONS: tuple[str, ...] = (identity.GRAPH_PERMISSION,)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {}

_DESCRIPTION = """\
Return the signed-in user's profile: user_id, display_name, email, user_principal_name, job_title. \
Call it before anything that depends on who "I", "me", or "my" is. Reuse the answer. It stays \
stable for the whole session. Match sender and recipient addresses on `email`. \
`user_principal_name` is a sign-in name on a possibly different domain, and it is correct only \
when `email` is null.\
"""


class SignedInUser(BaseModel):
    """The signed-in user's profile.

    Field names are snake_case. See field descriptions for Graph names.
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
            + "accounts. When null, use user_principal_name instead."
        )
    )
    user_principal_name: str | None = Field(
        description=(
            "The sign-in name (Graph userPrincipalName). It usually looks like an email address, "
            + "but it can be on a different domain. If email is null, use this field instead."
        )
    )
    job_title: str | None = Field(
        description="The user's job title from the directory. Null if the directory has none."
    )

    @classmethod
    def from_user(cls, user: User) -> Self:
        assert user.id is not None, "Graph answered GET /me with a user that has no id"
        return cls(
            user_id=user.id,
            display_name=user.display_name,
            email=user.mail,
            user_principal_name=user.user_principal_name,
            job_title=user.job_title,
        )


async def get_signed_in_user(client: GraphServiceClient) -> SignedInUser:
    """Return the caller's profile.

    `graph_errors` takes no `step=` here: the Graph call lives in `shared/identity.py`, which opens
    its own `graph_step`.
    """
    with graph_errors(TOOL_NAME):
        return SignedInUser.from_user(await identity.signed_in_user(client))


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Get My Profile",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def get_me(client: GraphServiceClient = graph) -> SignedInUser:
        return await get_signed_in_user(client)
