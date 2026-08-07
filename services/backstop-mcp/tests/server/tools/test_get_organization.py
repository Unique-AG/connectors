from collections.abc import Callable

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopResponseSchemaError
from backstop_mcp.features.data_hygiene import AsOf
from backstop_mcp.features.party_resolver import (
    PartyAmbiguousResponse,
    PartyCandidateResponse,
    ResolvedPartyResponse,
)
from backstop_mcp.features.resolution import NotFoundResponse
from backstop_mcp.server.tools.get_organization import (
    GetOrganizationResponse,
    OrganizationAttributes,
    OrganizationResolvedResponse,
    get_organization,
)
from tests.features.party_resolver.helpers import (
    BASE_URL,
    collection,
    ctx_decline,
    ctx_never_elicit,
    resource,
)
from tests.server.tools.helpers import tool_model, tool_model_union

type ConnectUser = Callable[..., object]


class TestGetOrganization:
    @pytest.mark.asyncio
    @respx.mock
    async def test_unique_search_fetches_organization_and_echoes_resolved(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-org-1", "org-bob.smith")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json=collection(resource("o42", "organizations", name="Capstone")),
            )
        )
        respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "type": "organizations",
                        "id": "o42",
                        "attributes": {
                            "name": "Capstone",
                            "status": "active",
                            "modifiedTimestamp": "2025-03-01T10:00:00Z",
                            "modifiedBy": "ops",
                        },
                    }
                },
            )
        )

        result = tool_model(
            await get_organization(ctx_never_elicit(), search="Capstone"),
            OrganizationResolvedResponse,
        )

        # `organization` is the record's own fields, not the enclosing JSON:API document —
        # `type`/`id` are already echoed under `resolved`.
        assert result.organization == OrganizationAttributes(
            name="Capstone",
            status="active",
            modified_timestamp="2025-03-01T10:00:00Z",
            modified_by="ops",
        )
        assert result.resolved == ResolvedPartyResponse(
            id="o42", search_type="organizations", name="Capstone"
        )
        assert result.as_of == AsOf(modified_timestamp="2025-03-01T10:00:00Z", modified_by="ops")

    @pytest.mark.asyncio
    @respx.mock
    async def test_ambiguous_search_returns_candidates_without_org_get(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-org-2", "org-carol.diaz")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json=collection(
                    resource("o1", "organizations", name="Capstone A"),
                    resource("o2", "organizations", name="Capstone B"),
                ),
            )
        )
        org_get = respx.get(url__regex=rf"{BASE_URL}/organizations/\w+").mock(
            return_value=httpx.Response(200, json={})
        )

        result = tool_model(
            await get_organization(ctx_decline(), search="Capstone"),
            PartyAmbiguousResponse,
        )

        assert result == PartyAmbiguousResponse(
            query="Capstone",
            scope="organizations",
            candidates=[
                PartyCandidateResponse(key="o1", label="Capstone A", id="o1", name="Capstone A"),
                PartyCandidateResponse(key="o2", label="Capstone B", id="o2", name="Capstone B"),
            ],
        )
        assert org_get.call_count == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_trusted_party_id_fetches_organization(self, connect_user: ConnectUser) -> None:
        await connect_user("user-org-3", "org-dave.lee")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(f"{BASE_URL}/organizations/trusted-9").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "type": "organizations",
                        "id": "trusted-9",
                        "attributes": {"name": "From Body"},
                    }
                },
            )
        )
        quick = respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=collection())
        )

        result = tool_model(
            await get_organization(ctx_never_elicit(), party_id="trusted-9"),
            OrganizationResolvedResponse,
        )

        # The name is backfilled from the organization fetch this tool makes anyway, so no
        # extra `confirm_name` request is needed to satisfy the echo requirement.
        assert result.resolved == ResolvedPartyResponse(
            id="trusted-9", search_type="organizations", name="From Body"
        )
        assert quick.call_count == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_trusted_party_id_is_percent_encoded_in_request_path(
        self, connect_user: ConnectUser
    ) -> None:
        # Defense in depth alongside the '/' rejection in resolve.py: any character that
        # could otherwise change the request's structure (here, a space) must be encoded
        # rather than interpolated raw into the path.
        await connect_user("user-org-5", "org-frank.oz")  # pyright: ignore[reportGeneralTypeIssues]

        org_get = respx.get(f"{BASE_URL}/organizations/trusted%209").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "type": "organizations",
                        "id": "trusted 9",
                        "attributes": {"name": "From Body"},
                    }
                },
            )
        )

        result = tool_model(
            await get_organization(ctx_never_elicit(), party_id="trusted 9"),
            OrganizationResolvedResponse,
        )

        assert isinstance(result, OrganizationResolvedResponse)
        assert org_get.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_trusted_party_id_containing_slash_is_rejected(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-org-6", "org-grace.hopper")  # pyright: ignore[reportGeneralTypeIssues]

        with pytest.raises(ValueError, match="must not contain '/'"):
            await get_organization(ctx_never_elicit(), party_id="../admin")

    @pytest.mark.asyncio
    @respx.mock
    async def test_malformed_organization_body_raises_schema_error(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-org-4", "org-erin.ng")  # pyright: ignore[reportGeneralTypeIssues]

        # `id` is entirely absent from the organization resource — fails
        # `BackstopApiResourceDocument[OrganizationAttributes]` schema validation outright.
        respx.get(f"{BASE_URL}/organizations/trusted-9").mock(
            return_value=httpx.Response(
                200,
                json={"data": {"type": "organizations", "attributes": {"name": "From Body"}}},
            )
        )

        with pytest.raises(BackstopResponseSchemaError) as exc_info:
            await get_organization(ctx_never_elicit(), party_id="trusted-9")

        assert exc_info.value.path == "/organizations/trusted-9"
        assert exc_info.value.schema_name == "BackstopApiResourceDocument[OrganizationAttributes]"

    @pytest.mark.asyncio
    @respx.mock
    async def test_not_found_search_returns_the_query_it_used(
        self, connect_user: ConnectUser
    ) -> None:
        """Policy step 5: name the exact term searched for, so a typo is correctable."""
        await connect_user("user-org-7", "org-hank.p")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=collection())
        )

        result = tool_model_union(
            await get_organization(ctx_never_elicit(), search="Capstoen"),
            GetOrganizationResponse,
        )

        assert isinstance(result, NotFoundResponse)
        assert result.status == "not_found"
        assert getattr(result, "query", None) == "Capstoen"
        assert getattr(result, "scope", None) == "organizations"
