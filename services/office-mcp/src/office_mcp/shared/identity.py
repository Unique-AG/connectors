"""Query who the signed-in user is.

This is the fact every other tool answer needs to correlate against.
"""

from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.user import User
from msgraph.generated.users.item.user_item_request_builder import UserItemRequestBuilder
from msgraph.graph_service_client import GraphServiceClient

from office_mcp.graph_client import graph_errors

GRAPH_PERMISSION = "User.Read"
PROFILE = ["id", "displayName", "mail", "userPrincipalName", "jobTitle"]

type _MeQuery = UserItemRequestBuilder.UserItemRequestBuilderGetQueryParameters


async def signed_in_user(client: GraphServiceClient) -> User:
    """Get the signed-in user from Graph, projected onto the promised properties."""
    configuration = RequestConfiguration[_MeQuery](
        query_parameters=UserItemRequestBuilder.UserItemRequestBuilderGetQueryParameters(
            select=PROFILE
        )
    )
    with graph_errors():
        user = await client.me.get(request_configuration=configuration)

    assert user is not None, "Graph answered GET /me with no user object"
    assert user.id is not None, "Graph answered GET /me with a user that has no id"
    return user
