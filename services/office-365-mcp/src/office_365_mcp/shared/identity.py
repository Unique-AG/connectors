"""Who the signed-in user is: the fact every other answer here is correlated against.

A meeting organiser can have a null display name in Graph, so a caller matches on Entra object id.
"""

from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.user import User
from msgraph.generated.users.item.user_item_request_builder import UserItemRequestBuilder
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import graph_step

# User.Read is the least-privileged delegated permission for /me. It needs no admin consent.
GRAPH_PERMISSION = "User.Read"

# `get_me` and `teams_list_meeting_recordings` both reach this call, and a step named by each of
# them
# would be the same request under two names.
STEP = "signed_in_user"

# /me returns 11 properties by default. This selects only the five get_me promises.
PROFILE = ["id", "displayName", "mail", "userPrincipalName", "jobTitle"]

type _MeQuery = UserItemRequestBuilder.UserItemRequestBuilderGetQueryParameters


async def signed_in_user(client: GraphServiceClient) -> User:
    """The signed-in user, projected onto `PROFILE`. Graph's own `User` rather than a shape of our
    own, which could not serve both a profile to report and an id to compare."""
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
