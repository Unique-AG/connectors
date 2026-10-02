"""`get_me`: the profile properties it publishes, over `shared/identity.py`'s Graph call."""

import httpx
import pytest
import respx
from fastmcp import FastMCP
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden
from office_365_mcp.tools import get_me

from .conftest import CALLER_TOKEN

_ME = {
    "id": "00000000-0000-4000-8000-000000000001",
    "displayName": "Ada Lovelace",
    "mail": "ada@example.invalid",
    "userPrincipalName": "ada@corp.example.invalid",
    "jobTitle": "Analyst",
    "givenName": "Ada",
    "surname": "Lovelace",
    "officeLocation": "18/2111",
    "businessPhones": ["+41 44 555 0109"],
    "mobilePhone": "+41 79 555 0109",
    "preferredLanguage": "en-US",
}


class TestTheProfileItReturns:
    async def test_it_asks_graph_only_for_the_properties_it_promises(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.get("/me").mock(return_value=httpx.Response(200, json=_ME))

        _ = await get_me.get_signed_in_user(client)

        selected = route.calls.last.request.url.params["$select"]
        assert selected.split(",") == [
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

    async def test_it_reports_the_email_and_the_upn_separately(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get("/me").mock(return_value=httpx.Response(200, json=_ME))

        user = await get_me.get_signed_in_user(client)

        assert user.email == "ada@example.invalid"
        assert user.user_principal_name == "ada@corp.example.invalid"
        assert user.user_id == "00000000-0000-4000-8000-000000000001"
        assert user.display_name == "Ada Lovelace"
        assert user.job_title == "Analyst"

    async def test_it_reports_the_name_parts_the_office_the_phones_and_the_language(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get("/me").mock(return_value=httpx.Response(200, json=_ME))

        user = await get_me.get_signed_in_user(client)

        assert user.given_name == "Ada"
        assert user.surname == "Lovelace"
        assert user.office_location == "18/2111"
        assert user.business_phones == ["+41 44 555 0109"]
        assert user.mobile_phone == "+41 79 555 0109"
        assert user.preferred_language == "en-US"

    async def test_a_guest_account_without_a_mailbox_still_answers(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get("/me").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "00000000-0000-4000-8000-000000000002",
                    "displayName": "Grace Hopper",
                    "mail": None,
                    "userPrincipalName": "grace_example.invalid#EXT#@corp.example.invalid",
                    "jobTitle": None,
                },
            )
        )

        user = await get_me.get_signed_in_user(client)

        assert user.email is None
        assert user.user_principal_name == "grace_example.invalid#EXT#@corp.example.invalid"
        assert user.business_phones == []

    @pytest.mark.parametrize("phones", [[], None])
    async def test_an_account_without_phone_numbers_answers_an_empty_list(
        self, client: GraphServiceClient, graph: respx.MockRouter, phones: list[str] | None
    ) -> None:
        body = {**_ME, "businessPhones": phones, "mobilePhone": None}
        graph.get("/me").mock(return_value=httpx.Response(200, json=body))

        user = await get_me.get_signed_in_user(client)

        assert user.business_phones == []
        assert user.mobile_phone is None

    async def test_it_calls_as_the_caller(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.get("/me").mock(return_value=httpx.Response(200, json=_ME))

        _ = await get_me.get_signed_in_user(client)

        assert route.calls.last.request.headers["authorization"] == f"Bearer {CALLER_TOKEN}"


class TestWhatItPublishes:
    async def test_the_description_names_the_recipient_lookup_behind_the_preset_guard(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        get_me.register(mcp, transport)

        tool = await mcp.get_tool(get_me.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        description = tool.description or ""
        assert (
            "If this deployment exposes outlook_find_recipient, that tool finds the address of "
            "somebody else"
        ) in description
        assert "directory or contacts lookup" not in description


class TestGraphFailures:
    async def test_a_refusal_arrives_classified(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get("/me").mock(
            return_value=httpx.Response(
                403,
                headers={"request-id": "synthetic-request-id"},
                json={"error": {"code": "Authorization_RequestDenied", "message": "no"}},
            )
        )

        with pytest.raises(GraphForbidden) as raised:
            _ = await get_me.get_signed_in_user(client)

        assert raised.value.status == 403
        assert raised.value.code == "Authorization_RequestDenied"
        assert raised.value.request_id == "synthetic-request-id"
