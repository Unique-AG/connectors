import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient, BackstopResponseSchemaError
from backstop_mcp.party_resolver import (
    BatchNeedsDisambiguation,
    BatchResolved,
    NeedsDisambiguation,
    NotFound,
    PartyResolveItem,
    QuickSearchOptions,
    Resolved,
    resolve_parties,
    resolve_party,
)
from tests.party_resolver.helpers import (
    BASE_URL,
    collection,
    ctx_decline,
    ctx_never_elicit,
    resource,
)


class TestTrustedPartyId:
    @pytest.mark.asyncio
    @respx.mock
    async def test_resolves_trusted_party_id_without_http(self, client: BackstopClient) -> None:
        result = await resolve_party(
            ctx_never_elicit(),
            client,
            search_type="organizations",
            party_id="org-123",
        )

        assert isinstance(result, Resolved)
        assert result.party.id == "org-123"
        assert result.party.type == "organizations"
        assert result.party.name is None
        assert len(respx.calls) == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_passes_through_optional_name_on_trusted_id(self, client: BackstopClient) -> None:
        result = await resolve_party(
            ctx_never_elicit(),
            client,
            search_type="people",
            party_id="person-9",
            name="Ada Lovelace",
        )

        assert isinstance(result, Resolved)
        assert result.party.id == "person-9"
        assert result.party.type == "people"
        assert result.party.name == "Ada Lovelace"
        assert len(respx.calls) == 0


class TestEmailSearch:
    @pytest.mark.asyncio
    @respx.mock
    async def test_email_search_for_people_hits_email_email2_email3_only(
        self, client: BackstopClient
    ) -> None:
        email = "ada@example.com"
        hit = httpx.Response(
            200,
            json=collection(resource("p1", "people", name="Ada Lovelace")),
        )
        email1 = respx.get(f"{BASE_URL}/people", params={"filter[email][eq]": email}).mock(
            return_value=hit
        )
        email2 = respx.get(f"{BASE_URL}/people", params={"filter[email2][eq]": email}).mock(
            return_value=httpx.Response(200, json=collection())
        )
        email3 = respx.get(f"{BASE_URL}/people", params={"filter[email3][eq]": email}).mock(
            return_value=httpx.Response(200, json=collection())
        )
        quick = respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=collection())
        )

        result = await resolve_party(
            ctx_never_elicit(),
            client,
            search_type="people",
            search=email,
        )

        assert isinstance(result, Resolved)
        assert result.party.id == "p1"
        assert email1.call_count == 1
        assert email2.call_count == 1
        assert email3.call_count == 1
        assert quick.call_count == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_email_search_for_organizations_uses_only_email_filter(
        self, client: BackstopClient
    ) -> None:
        email = "ops@capstone.com"
        orgs = respx.get(f"{BASE_URL}/organizations", params={"filter[email][eq]": email}).mock(
            return_value=httpx.Response(
                200,
                json=collection(resource("o1", "organizations", name="Capstone")),
            )
        )
        quick = respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=collection())
        )

        result = await resolve_party(
            ctx_never_elicit(),
            client,
            search_type="organizations",
            search=email,
        )

        assert isinstance(result, Resolved)
        assert result.party.id == "o1"
        assert orgs.call_count == 1
        assert orgs.calls.last.request.url.params["filter[email][eq]"] == email
        assert "filter[email2][eq]" not in orgs.calls.last.request.url.params
        assert quick.call_count == 0


class TestQuickSearch:
    @pytest.mark.asyncio
    @respx.mock
    async def test_name_search_uses_quick_search_defaults(self, client: BackstopClient) -> None:
        route = respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json=collection(resource("o1", "organizations", name="Capstone")),
            )
        )

        result = await resolve_party(
            ctx_never_elicit(),
            client,
            search_type="organizations",
            search="Capstone",
        )

        assert isinstance(result, Resolved)
        assert result.party.id == "o1"
        params = route.calls.last.request.url.params
        assert params["filter[searchText][eq]"] == "Capstone"
        assert params["filter[searchTypes][eq]"] == "organizations"
        assert params["filter[limit][eq]"] == "10"
        assert params["filter[showAll][eq]"] == "false"
        assert params["filter[enhanceSearchTypes][eq]"] == "false"
        assert params["page[limit]"] == "10"
        assert params["page[offset]"] == "0"
        assert "filter[fullEmailMatch][eq]" not in params
        assert "filter[filterType][eq]" not in params

    @pytest.mark.asyncio
    @respx.mock
    async def test_quick_search_option_overrides_appear_on_request(
        self, client: BackstopClient
    ) -> None:
        route = respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json=collection(resource("o1", "organizations", name="Capstone")),
            )
        )

        result = await resolve_party(
            ctx_never_elicit(),
            client,
            search_type="organizations",
            search="Capstone",
            quick_search_options=QuickSearchOptions(
                limit=5,
                show_all=True,
                enhance_search_types=True,
                full_email_match=False,
                filter_type="Accounts",
            ),
        )

        assert isinstance(result, Resolved)
        params = route.calls.last.request.url.params
        assert params["filter[limit][eq]"] == "5"
        assert params["page[limit]"] == "5"
        assert params["filter[showAll][eq]"] == "true"
        assert params["filter[enhanceSearchTypes][eq]"] == "true"
        assert params["filter[fullEmailMatch][eq]"] == "false"
        assert params["filter[filterType][eq]"] == "Accounts"

    @pytest.mark.asyncio
    @respx.mock
    async def test_blank_id_in_response_fails_schema_validation(
        self, client: BackstopClient
    ) -> None:
        # A present-but-blank id fails `BackstopApiResource`'s schema validation
        # (min_length=1, checked post-strip) — same failure mode as a missing id below,
        # since neither yields a usable resource identifier.
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json=collection(resource("", "organizations", name="Capstone")),
            )
        )

        with pytest.raises(BackstopResponseSchemaError) as exc_info:
            await resolve_party(
                ctx_never_elicit(),
                client,
                search_type="organizations",
                search="Capstone",
            )

        assert exc_info.value.path == "/quick-search"
        assert exc_info.value.schema_name == "BackstopApiDocument[PartyAttributes]"

    @pytest.mark.asyncio
    @respx.mock
    async def test_resource_missing_id_field_raises_schema_error(
        self, client: BackstopClient
    ) -> None:
        # `id` is entirely absent (not just blank) — fails `BackstopApiResource` schema
        # validation the same way a present-but-blank id does above.
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json={"data": [{"type": "organizations", "attributes": {"name": "Capstone"}}]},
            )
        )

        with pytest.raises(BackstopResponseSchemaError) as exc_info:
            await resolve_party(
                ctx_never_elicit(),
                client,
                search_type="organizations",
                search="Capstone",
            )

        assert exc_info.value.path == "/quick-search"
        assert exc_info.value.schema_name == "BackstopApiDocument[PartyAttributes]"


class TestHitCounts:
    @pytest.mark.asyncio
    @respx.mock
    async def test_zero_hits_returns_not_found(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=collection())
        )

        result = await resolve_party(
            ctx_never_elicit(),
            client,
            search_type="organizations",
            search="Unknown Co",
        )

        assert isinstance(result, NotFound)
        assert result.search == "Unknown Co"
        assert result.search_type == "organizations"

    @pytest.mark.asyncio
    @respx.mock
    async def test_one_hit_returns_resolved(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json=collection(resource("o1", "organizations", name="Capstone")),
            )
        )

        result = await resolve_party(
            ctx_never_elicit(),
            client,
            search_type="organizations",
            search="Capstone",
        )

        assert isinstance(result, Resolved)
        assert result.party.id == "o1"
        assert result.party.name == "Capstone"

    @pytest.mark.asyncio
    @respx.mock
    async def test_multiple_hits_enter_disambiguation_path(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json=collection(
                    resource("o1", "organizations", name="Capstone A"),
                    resource("o2", "organizations", name="Capstone B"),
                ),
            )
        )

        result = await resolve_party(
            ctx_decline(),
            client,
            search_type="organizations",
            search="Capstone",
        )

        assert isinstance(result, NeedsDisambiguation)
        assert len(result.candidates) == 2
        assert result.search == "Capstone"


class TestBatchResolve:
    @pytest.mark.asyncio
    @respx.mock
    async def test_batch_returns_one_payload_and_never_elicits(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/quick-search").mock(
            side_effect=[
                httpx.Response(200, json=collection()),
                httpx.Response(
                    200,
                    json=collection(
                        resource("o2", "organizations", name="Alpha"),
                        resource("o3", "organizations", name="Alpha Holdings"),
                    ),
                ),
            ]
        )

        result = await resolve_parties(
            ctx_never_elicit(),
            client,
            search_type="organizations",
            items=[
                PartyResolveItem(party_id="trusted-1", name="Trusted Org"),
                PartyResolveItem(search="Missing Co"),
                PartyResolveItem(search="Alpha"),
            ],
        )

        assert isinstance(result, BatchNeedsDisambiguation)
        assert len(result.resolved) == 1
        assert result.resolved[0].item_index == 0
        assert result.resolved[0].party.id == "trusted-1"
        assert result.resolved[0].party.name == "Trusted Org"
        assert len(result.unresolved) == 2
        assert result.unresolved[0].item_index == 1
        assert result.unresolved[0].candidates == ()
        assert result.unresolved[1].item_index == 2
        assert len(result.unresolved[1].candidates) == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_batch_all_resolved_returns_batch_resolved(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json=collection(resource("o1", "organizations", name="Solo")),
            )
        )

        result = await resolve_parties(
            ctx_never_elicit(),
            client,
            search_type="organizations",
            items=[
                PartyResolveItem(party_id="trusted-1"),
                PartyResolveItem(search="Solo"),
            ],
        )

        assert isinstance(result, BatchResolved)
        assert [party.id for party in result.parties] == ["trusted-1", "o1"]


class TestInvalidArgs:
    @pytest.mark.asyncio
    async def test_rejects_both_party_id_and_search(self, client: BackstopClient) -> None:
        with pytest.raises(ValueError, match="Exactly one of party_id or search"):
            await resolve_party(
                ctx_never_elicit(),
                client,
                search_type="organizations",
                party_id="o1",
                search="Capstone",
            )

    @pytest.mark.asyncio
    async def test_rejects_neither_party_id_nor_search(self, client: BackstopClient) -> None:
        with pytest.raises(ValueError, match="Exactly one of party_id or search"):
            await resolve_party(
                ctx_never_elicit(),
                client,
                search_type="organizations",
            )

    @pytest.mark.asyncio
    async def test_rejects_party_id_containing_slash(self, client: BackstopClient) -> None:
        # A trusted party_id is never existence-checked and later gets interpolated into a
        # request path (e.g. `/organizations/{id}`) — a '/' could redirect that request to
        # an unintended path/endpoint, so it's rejected here rather than trusted blindly.
        with pytest.raises(ValueError, match="must not contain '/'"):
            await resolve_party(
                ctx_never_elicit(),
                client,
                search_type="organizations",
                party_id="../admin",
            )

    def test_party_resolve_item_rejects_both(self) -> None:
        with pytest.raises(ValueError, match="Exactly one of party_id or search"):
            PartyResolveItem(party_id="o1", search="Capstone")

    def test_party_resolve_item_rejects_neither(self) -> None:
        with pytest.raises(ValueError, match="Exactly one of party_id or search"):
            PartyResolveItem()
