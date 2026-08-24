"""`get_me`: the five properties it publishes, over `shared/identity.py`'s Graph call."""

import httpx
import pytest
import respx
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
}


class TestTheProfileItReturns:
    async def test_it_asks_graph_only_for_the_properties_it_promises(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.get("/me").mock(return_value=httpx.Response(200, json=_ME))

        _ = await get_me.get_signed_in_user(client)

        selected = route.calls.last.request.url.params["$select"]
        assert selected.split(",") == ["id", "displayName", "mail", "userPrincipalName", "jobTitle"]

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

    async def test_it_calls_as_the_caller(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.get("/me").mock(return_value=httpx.Response(200, json=_ME))

        _ = await get_me.get_signed_in_user(client)

        assert route.calls.last.request.headers["authorization"] == f"Bearer {CALLER_TOKEN}"


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
