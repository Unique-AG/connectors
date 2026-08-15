"""Who the signed-in user is, as one question with one answer.

`get_me` exists to answer it, and today it is the only tool that asks — which is the whole reason
to be careful about where the asking lives. The *question* is here: which endpoint answers it,
under which permission, projected onto which properties. The *answer shape* is not: `get_me` owns
`SignedInUser`, its field names and the prose that teaches a model when `email` is null and what to
use instead, because that shape is the tool's own product and nothing else returns it.

Splitting the two now, rather than on the day a second tool asks, is deliberate. "Who am I" is what
every other answer on this connector is correlated against, and the next tool to want it wants one
id rather than a profile — an organiser to compare a caller against, say, which Graph reports with
a null display name and so can only be matched on the Entra object id. Asked as a `GET /me` of its
own under a projection of its own, that would be a second answer to one question. It costs nothing
to decide there is one while there is one caller, and it costs a caller-visible disagreement later.

`User.Read` is the least-privileged delegated permission for `/me` and needs no admin consent,
which is why a tool that wants a single fact off it can afford to spend it.
"""

from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.user import User
from msgraph.generated.users.item.user_item_request_builder import UserItemRequestBuilder
from msgraph.graph_service_client import GraphServiceClient

from office_mcp.graph_client import graph_errors

# The delegated Microsoft Graph permission this one call needs. Declared beside the call rather than
# in each tool that makes it so that the permission and the request cannot drift apart — a tool
# still names it in its own `GRAPH_PERMISSIONS`, which is what reaches sign-in and what a refusal
# is worded from.
GRAPH_PERMISSION = "User.Read"

# `/me` returns a large default projection; these are the five properties `get_me` promises. One
# projection rather than one per caller: a second, narrower `$select` would be a second request
# shape to keep in step with the answer shape, and this one is already the cheapest useful call.
PROFILE = ["id", "displayName", "mail", "userPrincipalName", "jobTitle"]

type _MeQuery = UserItemRequestBuilder.UserItemRequestBuilderGetQueryParameters


async def signed_in_user(client: GraphServiceClient) -> User:
    """`GET /me`, projected onto the properties this connector promises.

    Graph's own `user` rather than a shape of ours: its callers want different things from it — a
    profile to report and an id to compare — and a type in the middle would have to be whichever of
    those it was designed for.
    """
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
