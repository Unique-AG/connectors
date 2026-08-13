"""Who the caller is, according to Microsoft Graph.

Every other feature answers questions about "my" mail, "my" chats or "my" meetings, and each of
them is answered as the signed-in user. This module is how a model finds out who that is.
"""

from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.users.item.user_item_request_builder import UserItemRequestBuilder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_mcp.graph_client import graph_errors

# The delegated Microsoft Graph permission this module's one call needs. Declared beside the call
# rather than in the server layer so that the permission and the request that requires it cannot
# drift apart: `server/` both requests it at sign-in and names it when Graph refuses.
GRAPH_PERMISSION = "User.Read"

# `/me` returns a large default projection; these are the five properties the model is told about.
_SELECT = ["id", "displayName", "mail", "userPrincipalName", "jobTitle"]

type _MeQuery = UserItemRequestBuilder.UserItemRequestBuilderGetQueryParameters


class SignedInUser(BaseModel):
    """The signed-in user's own profile, as the MCP client sees it.

    Field names are snake_case here and in every other tool payload, which is the one place this
    connector deliberately does not echo Graph's spelling — the field descriptions name the Graph
    property wherever the two differ.
    """

    id: str = Field(
        description=(
            "The user's immutable Microsoft Entra object id (Graph `id`). The only identifier "
            + "safe to compare against user ids from other tools; names and addresses change."
        )
    )
    display_name: str | None = Field(
        description="The user's name as Microsoft 365 shows it. Null only on incomplete accounts."
    )
    mail: str | None = Field(
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
            + "`mail`, so treat it as an identifier rather than an address unless `mail` is null."
        )
    )
    job_title: str | None = Field(
        description="The user's job title, when the directory records one."
    )


async def get_signed_in_user(client: GraphServiceClient) -> SignedInUser:
    """`GET /me`, projected onto the five properties this connector promises."""
    configuration = RequestConfiguration[_MeQuery](
        query_parameters=UserItemRequestBuilder.UserItemRequestBuilderGetQueryParameters(
            select=_SELECT
        )
    )
    with graph_errors():
        user = await client.me.get(request_configuration=configuration)

    assert user is not None, "Graph answered GET /me with no user object"
    assert user.id is not None, "Graph answered GET /me with a user that has no id"
    return SignedInUser(
        id=user.id,
        display_name=user.display_name,
        mail=user.mail,
        user_principal_name=user.user_principal_name,
        job_title=user.job_title,
    )
