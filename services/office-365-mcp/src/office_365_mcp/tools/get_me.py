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
Returns the signed-in user's own Microsoft 365 profile: id, display name, email, sign-in name, \
and job title. This tool applies when a request depends on who "I", "me", or "my" refers to. \
It describes only the caller. Resolve someone else's address with a directory or contacts \
lookup instead.\
"""


class SignedInUser(BaseModel):
    """The signed-in user's profile.

    Field names are snake_case. See field descriptions for Graph names.
    """

    user_id: str = Field(
        description=(
            "The user's immutable Entra object id (Graph `id`), stable even if the user's display "
            + "name or email changes. Compare identity only against another `user_id`, never "
            + "against an email address or name."
        )
    )
    display_name: str | None = Field(
        description=(
            "The user's display name as Microsoft 365 shows it. It is null only for an "
            + "incomplete account."
        )
    )
    email: str | None = Field(
        description=(
            "The user's canonical primary SMTP address (Graph `mail`). The address is null for "
            + "guest and unlicensed accounts. If it is null, use `user_principal_name` instead. "
            + "Match sender and recipient addresses elsewhere against this field."
        )
    )
    user_principal_name: str | None = Field(
        description=(
            "The user's sign-in name (Graph `userPrincipalName`). It is null only if the account "
            + "has no sign-in name. It can be on a different domain than `email`."
        )
    )
    job_title: str | None = Field(
        description=(
            "The user's job title from the directory. It is null if the directory has none on "
            + "file."
        )
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
