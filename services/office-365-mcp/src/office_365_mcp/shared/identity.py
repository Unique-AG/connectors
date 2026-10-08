"""Who the signed-in user is: the fact every other answer here is checked against.

A meeting organizer can have a null display name in Graph. For that reason, a caller matches on
the Entra object id.
"""

from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.user import User
from msgraph.generated.users.item.user_item_request_builder import UserItemRequestBuilder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_step
from office_365_mcp.shared.prose import cut_for_a_question

# User.Read is the least-privileged delegated permission for /me. It needs no admin consent.
GRAPH_PERMISSION = "User.Read"

ENTRA_OBJECT_ID_PATTERN = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# `get_me` and `teams_list_meeting_recordings` both reach this call. If each one names its own
# step, one request carries two names, so they share `STEP` instead.
STEP = "signed_in_user"

PROFILE = [
    "id",
    "displayName",
    "givenName",
    "surname",
    "mail",
    "userPrincipalName",
    "jobTitle",
    "officeLocation",
    "businessPhones",
    "mobilePhone",
    "preferredLanguage",
]

type _MeQuery = UserItemRequestBuilder.UserItemRequestBuilderGetQueryParameters


class Person(BaseModel, frozen=True):
    user_id: str = Field(
        pattern=ENTRA_OBJECT_ID_PATTERN,
        description=(
            "The Microsoft Entra object id of the person, as a GUID. Copy it from the `user_id` of "
            + "get_me, of a teams_list_chat_members row, or of a teams_list_chats member. Never "
            + "build it from a name or an email address."
        ),
    )
    name: str = Field(
        min_length=1,
        description=(
            "The name of the person, as a label only. Teams identifies the person only by "
            + "`user_id`. Copy the `display_name` from the same result as `user_id`. If that "
            + "result has no display name, copy its sign-in name or its email address. This tool "
            + "shows the name to the user in its question, beside `user_id`, and never sends it "
            + "to Microsoft 365."
        ),
    )


def person_in_question(user_id: str, name: str) -> str:
    return _with_object_id(
        user_id, f"the name {cut_for_a_question(name)!r} is only a label from the request"
    )


def member_in_question(user_id: str, name: str) -> str:
    return _with_object_id(
        user_id, f"the name {cut_for_a_question(name)!r} comes from Microsoft 365"
    )


def _with_object_id(user_id: str, named: str) -> str:
    return f"the person with the Microsoft Entra object id {user_id!r} ({named})"


def user_bind(user_id: str) -> dict[str, str]:
    return {"user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{user_id}')"}


async def signed_in_user(client: GraphServiceClient) -> User:
    """The signed-in user, projected onto `PROFILE`.

    This returns Graph's own `User` type instead of a custom shape. A custom shape cannot serve
    both as a profile to report and as an id to compare.
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
