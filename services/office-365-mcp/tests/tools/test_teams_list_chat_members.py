from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.tools import Tool
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared.seam import READ_ONLY
from office_365_mcp.tools import teams_list_chat_members as lister

from .conftest import GRAPH_V1, OTHER_USER_ID, SIGNED_IN_USER_ID

_CHAT_ID = "19:release@thread.v2"
_MEMBERS_PATH = "/chats/19%3Arelease%40thread.v2/members"
_NEXT_PAGE = f"{GRAPH_V1}{_MEMBERS_PATH}?$skiptoken=synthetic"

_OWNER_MEMBERSHIP_ID = "MCMjMCMjc3ludGhldGljLW93bmVy"
_MEMBER_MEMBERSHIP_ID = "MCMjMCMjc3ludGhldGljLW1lbWJlcg=="
_VISITOR_MEMBERSHIP_ID = "MCMjMCMjc3ludGhldGljLXZpc2l0b3I="


def _entra_member(
    *,
    membership_id: str = _OWNER_MEMBERSHIP_ID,
    user_id: str | None = SIGNED_IN_USER_ID,
    display_name: str | None = "Ada Lovelace",
    email: str | None = "ada@example.invalid",
    roles: Sequence[str] = ("owner",),
) -> dict[str, object]:
    return {
        "@odata.type": "#microsoft.graph.aadUserConversationMember",
        "id": membership_id,
        "roles": list(roles),
        "displayName": display_name,
        "visibleHistoryStartDateTime": "2026-02-11T09:15:22.31Z",
        "userId": user_id,
        "email": email,
        "tenantId": "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81",
    }


def _page(*members: Mapping[str, object], next_link: str | None = None) -> httpx.Response:
    body: dict[str, object] = {"value": [dict(member) for member in members]}
    if next_link is not None:
        body["@odata.nextLink"] = next_link
    return httpx.Response(200, json=body)


def _lists(graph: respx.MockRouter, response: httpx.Response | None = None) -> respx.Route:
    return graph.get(_MEMBERS_PATH).mock(
        return_value=response if response is not None else _page(_entra_member())
    )


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    lister.register(mcp, transport)
    tool = await mcp.get_tool(lister.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


def _property(parameters: Mapping[str, object], name: str) -> Mapping[str, object]:
    return cast(
        "Mapping[str, object]", cast("Mapping[str, object]", parameters["properties"])[name]
    )


class TestTheRequestItSends:
    async def test_it_reads_the_members_of_the_chat_in_one_request_with_no_query(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _lists(graph)

        _ = await lister.teams_list_chat_members(client, chat_id=_CHAT_ID)

        assert len(graph.calls) == 1, "one call is one request against the chat"
        request = route.calls.last.request
        assert request.method == "GET"
        assert str(request.url) == f"{GRAPH_V1}{_MEMBERS_PATH}"
        assert request.url.query == b""


class TestOneCallIsOneRequest:
    async def test_microsofts_cursor_is_read_and_never_followed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        second_page = graph.get(_MEMBERS_PATH, params={"$skiptoken": "synthetic"}).mock(
            return_value=_page(_entra_member(membership_id=_MEMBER_MEMBERSHIP_ID))
        )
        _ = _lists(graph, _page(_entra_member(), next_link=_NEXT_PAGE))

        listed = await lister.teams_list_chat_members(client, chat_id=_CHAT_ID)

        assert len(graph.calls) == 1, "one call is one request against the chat"
        assert not second_page.called
        assert listed.more_members is True
        assert len(listed.members) == 1

    async def test_a_page_with_no_cursor_says_the_list_is_complete(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _lists(graph)

        listed = await lister.teams_list_chat_members(client, chat_id=_CHAT_ID)

        assert listed.more_members is False


class TestWhatItAnswers:
    async def test_a_microsoft_entra_member_maps_every_field(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _lists(graph)

        listed = await lister.teams_list_chat_members(client, chat_id=_CHAT_ID)

        assert [member.model_dump() for member in listed.members] == [
            {
                "membership_id": _OWNER_MEMBERSHIP_ID,
                "user_id": SIGNED_IN_USER_ID,
                "display_name": "Ada Lovelace",
                "email": "ada@example.invalid",
                "roles": ["owner"],
            }
        ]

    async def test_the_rows_keep_the_order_graph_sent_them_in(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _lists(
            graph,
            _page(
                _entra_member(membership_id=_MEMBER_MEMBERSHIP_ID, user_id=OTHER_USER_ID),
                _entra_member(membership_id=_OWNER_MEMBERSHIP_ID),
            ),
        )

        listed = await lister.teams_list_chat_members(client, chat_id=_CHAT_ID)

        assert [member.membership_id for member in listed.members] == [
            _MEMBER_MEMBERSHIP_ID,
            _OWNER_MEMBERSHIP_ID,
        ]
        assert [member.user_id for member in listed.members] == [OTHER_USER_ID, SIGNED_IN_USER_ID]

    async def test_the_membership_id_is_not_the_user_id(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _lists(graph)

        listed = await lister.teams_list_chat_members(client, chat_id=_CHAT_ID)

        member = listed.members[0]
        assert member.membership_id == _OWNER_MEMBERSHIP_ID
        assert member.user_id == SIGNED_IN_USER_ID

    @pytest.mark.parametrize(
        ("roles", "expected"),
        [(["owner"], ["owner"]), (["guest"], ["guest"]), (["owner", "guest"], ["owner", "guest"])],
        ids=["owner", "guest", "both"],
    )
    async def test_the_roles_are_copied_as_microsoft_sent_them(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        roles: list[str],
        expected: list[str],
    ) -> None:
        _ = _lists(graph, _page(_entra_member(roles=roles)))

        listed = await lister.teams_list_chat_members(client, chat_id=_CHAT_ID)

        assert listed.members[0].roles == expected

    async def test_an_ordinary_member_has_an_empty_role_list(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _lists(graph, _page(_entra_member(roles=())))

        listed = await lister.teams_list_chat_members(client, chat_id=_CHAT_ID)

        assert listed.members[0].roles == []

    @pytest.mark.parametrize(
        "member",
        [
            {
                "@odata.type": "#microsoft.graph.anonymousGuestConversationMember",
                "id": _VISITOR_MEMBERSHIP_ID,
                "displayName": "Visitor",
                "roles": ["guest"],
                "anonymousGuestId": "synthetic-guest-id",
            },
            {
                "@odata.type": "#microsoft.graph.microsoftAccountUserConversationMember",
                "id": _VISITOR_MEMBERSHIP_ID,
                "displayName": "Visitor",
                "roles": ["guest"],
                "userId": OTHER_USER_ID,
            },
            {
                "@odata.type": "#microsoft.graph.skypeUserConversationMember",
                "id": _VISITOR_MEMBERSHIP_ID,
                "displayName": "Visitor",
                "roles": ["guest"],
                "skypeId": "live:synthetic",
            },
            {"id": _VISITOR_MEMBERSHIP_ID, "displayName": "Visitor", "roles": ["guest"]},
        ],
        ids=["anonymous-guest", "microsoft-account", "skype", "no-type"],
    )
    async def test_a_member_without_an_entra_account_has_no_user_id_and_no_email(
        self, client: GraphServiceClient, graph: respx.MockRouter, member: dict[str, object]
    ) -> None:
        _ = _lists(graph, _page(member))

        listed = await lister.teams_list_chat_members(client, chat_id=_CHAT_ID)

        assert [row.model_dump() for row in listed.members] == [
            {
                "membership_id": _VISITOR_MEMBERSHIP_ID,
                "user_id": None,
                "display_name": "Visitor",
                "email": None,
                "roles": ["guest"],
            }
        ]

    async def test_a_member_with_no_display_name_has_a_null_one(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _lists(graph, _page(_entra_member(display_name=None, email=None)))

        listed = await lister.teams_list_chat_members(client, chat_id=_CHAT_ID)

        assert listed.members[0].display_name is None
        assert listed.members[0].email is None
        assert listed.members[0].user_id == SIGNED_IN_USER_ID

    async def test_a_chat_with_no_members_is_an_empty_list_not_a_failure(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _lists(graph, _page())

        listed = await lister.teams_list_chat_members(client, chat_id=_CHAT_ID)

        assert listed.members == []
        assert listed.more_members is False


class TestGraphFailures:
    async def test_a_refusal_arrives_classified_for_the_tool_to_explain(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _lists(
            graph,
            httpx.Response(403, json={"error": {"code": "Forbidden", "message": "denied"}}),
        )

        with pytest.raises(GraphForbidden):
            _ = await lister.teams_list_chat_members(client, chat_id=_CHAT_ID)

    async def test_a_chat_graph_will_not_return_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _lists(
            graph,
            httpx.Response(404, json={"error": {"code": "NotFound", "message": "no such chat"}}),
        )

        with pytest.raises(GraphNotFound):
            _ = await lister.teams_list_chat_members(client, chat_id=_CHAT_ID)


class TestHowItDeclaresItself:
    def test_the_permission_is_chat_read_and_nothing_wider(self) -> None:
        assert lister.GRAPH_PERMISSIONS == ("Chat.Read",)

    async def test_it_announces_itself_as_read_only(self, transport: httpx.AsyncClient) -> None:
        _parameters, tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is READ_ONLY["readOnlyHint"]
        assert annotations.open_world_hint is READ_ONLY["openWorldHint"]

    async def test_the_only_argument_is_a_required_chat_id(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        assert set(cast("Mapping[str, object]", parameters["properties"])) == {"chat_id"}
        assert list(cast("Sequence[str]", parameters["required"])) == ["chat_id"]
        assert _property(parameters, "chat_id")["minLength"] == 1

    async def test_the_chat_id_description_names_the_sibling_that_reports_it(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        description = cast("str", _property(parameters, "chat_id")["description"])
        assert "`chat_id` that teams_list_chats reported" in description
        assert "It is not a `teams:///` handle." in description

    async def test_the_description_names_the_sibling_and_says_it_reads_one_page(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "teams_list_chats is the sibling tool that lists the chats." in description
        assert "That tool shows members only for unnamed chats." in description
        assert "This tool reads one page of members." in description
        assert "If `more_members` is true" in description
        assert "Calling it again returns the same members." in description

    async def test_the_description_says_a_member_without_an_entra_account_has_no_id_or_email(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "A member without a Microsoft Entra account" in description
        assert "has a null `user_id` and a null `email`" in description
