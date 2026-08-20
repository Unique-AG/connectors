"""Query who the signed-in user is.

This is the fact every other tool answer needs to correlate against.

Example: a meeting organiser can have a null display name in Graph. A future caller must then \
match the organiser by Entra object id instead.
"""

from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.user import User
from msgraph.generated.users.item.user_item_request_builder import UserItemRequestBuilder
from msgraph.graph_service_client import GraphServiceClient

from office_mcp.graph_client import graph_step

# User.Read is the least-privileged delegated permission for /me. It needs no admin consent.
GRAPH_PERMISSION = "User.Read"

# What this module's one Graph call is counted as. Declared here rather than by the tools, because
# this module owns the call: `get_me` and `list_meeting_recordings` both reach it, and a step named
# by each of them would be the same request under two names.
STEP = "signed_in_user"

# /me returns 11 properties by default. This selects only the five get_me promises.
PROFILE = ["id", "displayName", "mail", "userPrincipalName", "jobTitle"]

type _MeQuery = UserItemRequestBuilder.UserItemRequestBuilderGetQueryParameters


async def signed_in_user(client: GraphServiceClient) -> User:
    """Get the signed-in user from Graph, projected onto the promised properties.

    Returns Graph's own User type, not a shape of our own. One caller wants a profile to
    report. A future caller wants only an id to compare. One custom type could not serve both.
    """
    configuration = RequestConfiguration[_MeQuery](
        query_parameters=UserItemRequestBuilder.UserItemRequestBuilderGetQueryParameters(
            select=PROFILE
        )
    )
    with graph_step(STEP):
        user = await client.me.get(request_configuration=configuration)

    assert user is not None, "Graph answered GET /me with no user object"
    assert user.id is not None, "Graph answered GET /me with a user that has no id"
    return user
