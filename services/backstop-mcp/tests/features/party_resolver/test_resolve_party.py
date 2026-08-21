import asyncio

import httpx
import pytest
import respx
from fastmcp.server.elicitation import AcceptedElicitation
from mcp.shared.exceptions import McpError
from mcp.types import METHOD_NOT_FOUND, ClientCapabilities, ErrorData

from backstop_mcp.backstop_client import BackstopClient, BackstopResponseSchemaError
from backstop_mcp.features.party_resolver import (
    PartyResolveItemDto,
    QuickSearchOptionsDto,
    ResolvedPartyDto,
    resolve_parties,
    resolve_party,
    unresolved_parties_response,
    unresolved_party_response,
)
from backstop_mcp.features.resolution import (
    Ambiguous,
    BatchAmbiguous,
    BatchResolved,
    Candidate,
    NotFound,
    NotFoundResponse,
    Resolved,
    elicit_choice,
)
from tests.features.party_resolver.helpers import (
    BASE_URL,
    FakeContext,
    as_context,
    collection,
    ctx_accept,
    ctx_cancel,
    ctx_decline,
    ctx_never_elicit,
    ctx_no_elicitation_capability,
    ctx_unsupported,
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
        assert result.value.id == "org-123"
        assert result.value.search_type == "organizations"
        assert result.value.name is None
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
        assert result.value.id == "person-9"
        assert result.value.search_type == "people"
        assert result.value.name == "Ada Lovelace"
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
        assert result.value.id == "p1"
        assert email1.call_count == 1
        assert email2.call_count == 1
        assert email3.call_count == 1
        assert quick.call_count == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_display_name_email_filters_on_normalized_address(
        self, client: BackstopClient
    ) -> None:
        """Display-name forms must exact-filter on the bare address, not the raw string."""
        raw = '"Ada Lovelace" <ada@example.com>'
        normalized = "ada@example.com"
        email1 = respx.get(f"{BASE_URL}/people", params={"filter[email][eq]": normalized}).mock(
            return_value=httpx.Response(
                200,
                json=collection(resource("p1", "people", name="Ada Lovelace")),
            )
        )
        respx.get(f"{BASE_URL}/people", params={"filter[email2][eq]": normalized}).mock(
            return_value=httpx.Response(200, json=collection())
        )
        respx.get(f"{BASE_URL}/people", params={"filter[email3][eq]": normalized}).mock(
            return_value=httpx.Response(200, json=collection())
        )
        # A raw-string filter must never be issued — that would miss Backstop's stored address.
        raw_filter = respx.get(f"{BASE_URL}/people", params={"filter[email][eq]": raw}).mock(
            return_value=httpx.Response(200, json=collection())
        )

        result = await resolve_party(
            ctx_never_elicit(),
            client,
            search_type="people",
            search=raw,
        )

        assert isinstance(result, Resolved)
        assert result.value.id == "p1"
        assert email1.call_count == 1
        assert raw_filter.call_count == 0

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
        assert result.value.id == "o1"
        assert orgs.call_count == 1
        assert orgs.calls.last.request.url.params["filter[email][eq]"] == email
        assert "filter[email2][eq]" not in orgs.calls.last.request.url.params
        assert quick.call_count == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_surrounding_whitespace_is_stripped_before_filtering(
        self, client: BackstopClient
    ) -> None:
        email = "bob@example.com"
        respx.get(f"{BASE_URL}/people", params={"filter[email][eq]": email}).mock(
            return_value=httpx.Response(
                200,
                json=collection(resource("p1", "people", name="Bob")),
            )
        )
        respx.get(f"{BASE_URL}/people", params={"filter[email2][eq]": email}).mock(
            return_value=httpx.Response(200, json=collection())
        )
        respx.get(f"{BASE_URL}/people", params={"filter[email3][eq]": email}).mock(
            return_value=httpx.Response(200, json=collection())
        )

        result = await resolve_party(
            ctx_never_elicit(),
            client,
            search_type="people",
            search="  bob@example.com  ",
        )

        assert isinstance(result, Resolved)
        assert result.value.id == "p1"

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_plain_name_does_not_hit_email_filters(self, client: BackstopClient) -> None:
        email_route = respx.get(f"{BASE_URL}/people").mock(
            return_value=httpx.Response(200, json=collection())
        )
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json=collection(resource("p1", "people", name="Capstone Partners")),
            )
        )

        result = await resolve_party(
            ctx_never_elicit(),
            client,
            search_type="people",
            search="Capstone Partners",
        )

        assert isinstance(result, Resolved)
        assert result.value.id == "p1"
        assert email_route.call_count == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_string_that_is_not_an_email_goes_to_quick_search(
        self, client: BackstopClient
    ) -> None:
        quick = respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=collection())
        )
        like = respx.get(f"{BASE_URL}/people").mock(
            return_value=httpx.Response(200, json=collection())
        )

        await resolve_party(
            ctx_never_elicit(),
            client,
            search_type="people",
            search="@example.com",
        )

        assert quick.call_count == 1
        assert like.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_malformed_email_hit_raises_schema_error(self, client: BackstopClient) -> None:
        email = "ops@capstone.com"
        respx.get(f"{BASE_URL}/organizations", params={"filter[email][eq]": email}).mock(
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
                search=email,
            )

        assert exc_info.value.path == "/organizations"
        assert exc_info.value.schema_name == "BackstopApiCollectionDocument[PartyAttributes]"


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
        assert result.value.id == "o1"
        params = route.calls.last.request.url.params
        assert params["filter[searchText][eq]"] == "Capstone"
        assert params["filter[searchTypes][eq]"] == "ORGANIZATION"
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
            quick_search_options=QuickSearchOptionsDto(
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
    async def test_enhanced_quick_search_preserves_resource_search_type(
        self, client: BackstopClient
    ) -> None:
        # With enhance_search_types, /quick-search can return other party kinds. The
        # candidate's search_type must follow the resource, not the requested scope —
        # otherwise a later trusted-id fetch hits the wrong collection.
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json=collection(resource("p1", "people", name="Jane Doe")),
            )
        )

        result = await resolve_party(
            ctx_never_elicit(),
            client,
            search_type="organizations",
            search="Jane",
            quick_search_options=QuickSearchOptionsDto(enhance_search_types=True),
        )

        assert isinstance(result, Resolved)
        assert result.value.id == "p1"
        assert result.value.search_type == "people"
        assert result.value.name == "Jane Doe"

    @pytest.mark.asyncio
    @respx.mock
    async def test_ambiguous_enhanced_candidates_expose_resource_search_type(
        self, client: BackstopClient
    ) -> None:
        """Cross-type ambiguous hits must carry each candidate's own search_type."""
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json=collection(
                    resource("p1", "people", name="Jane A"),
                    resource("o2", "organizations", name="Jane Holdings"),
                ),
            )
        )

        result = await resolve_party(
            ctx_never_elicit(),
            client,
            search_type="organizations",
            search="Jane",
            quick_search_options=QuickSearchOptionsDto(enhance_search_types=True),
        )
        assert isinstance(result, Ambiguous)

        response = unresolved_party_response(result)
        assert not isinstance(response, NotFoundResponse)
        assert [c.id for c in response.candidates] == ["p1", "o2"]
        assert [c.search_type for c in response.candidates] == ["people", "organizations"]
        assert [c.key for c in response.candidates] == ["people:p1", "organizations:o2"]
        assert [c.label for c in response.candidates] == [
            "Jane A (person)",
            "Jane Holdings (organization)",
        ]

    @pytest.mark.asyncio
    @respx.mock
    async def test_enhanced_same_id_across_types_keeps_both_candidates(
        self, client: BackstopClient
    ) -> None:
        """Backstop ids are per-collection; the elicit key must not collapse cross-type hits."""
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json=collection(
                    resource("1", "people", name="Jane"),
                    resource("1", "organizations", name="Jane"),
                ),
            )
        )

        result = await resolve_party(
            ctx_never_elicit(),
            client,
            search_type="organizations",
            search="Jane",
            quick_search_options=QuickSearchOptionsDto(enhance_search_types=True),
        )
        assert isinstance(result, Ambiguous)

        response = unresolved_party_response(result)
        assert not isinstance(response, NotFoundResponse)
        assert [c.id for c in response.candidates] == ["1", "1"]
        assert [c.search_type for c in response.candidates] == ["people", "organizations"]
        assert [c.key for c in response.candidates] == ["people:1", "organizations:1"]
        assert [c.label for c in response.candidates] == [
            "Jane (person)",
            "Jane (organization)",
        ]

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
        assert exc_info.value.schema_name == "BackstopApiCollectionDocument[PartyAttributes]"

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
        assert exc_info.value.schema_name == "BackstopApiCollectionDocument[PartyAttributes]"


class TestCandidateLabel:
    """The elicit enum and the ambiguous payload both name the entity kind next to the hit."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_named_hits_carry_the_singular_kind(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json=collection(
                    resource("o1", "organizations", name="Koch"),
                    resource("p1", "people", name="Voss, Kent"),
                    resource("c1", "contacts", name="Voss, Kent"),
                    resource("e1", "employees", name="Lucas, Margaret"),
                ),
            )
        )

        result = await resolve_party(
            ctx_decline(),
            client,
            search_type="organizations",
            search="Koch",
            quick_search_options=QuickSearchOptionsDto(enhance_search_types=True),
        )

        assert isinstance(result, Ambiguous)
        assert [candidate.label for candidate in result.candidates] == [
            "Koch (organization)",
            "Voss, Kent (person)",
            "Voss, Kent (contact)",
            "Lucas, Margaret (employee)",
        ]

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_hit_without_a_name_still_names_the_kind(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json=collection(
                    resource("o42", "organizations"),
                    resource("o43", "organizations"),
                ),
            )
        )

        result = await resolve_party(
            ctx_decline(),
            client,
            search_type="organizations",
            search="unknown",
        )

        assert isinstance(result, Ambiguous)
        assert [candidate.label for candidate in result.candidates] == [
            "organization #o42",
            "organization #o43",
        ]


class TestSearchTypeMapping:
    """`/quick-search` rejects our lowercase `SearchType` outright (400 InvalidParameterException);
    it wants its own uppercase enum. Driven through `resolve_party` with a name, which is the
    production path that reaches quick-search.
    """

    @pytest.mark.asyncio
    @respx.mock
    async def test_organizations_maps_to_organization(self, client: BackstopClient) -> None:
        route = respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=collection())
        )
        respx.get(f"{BASE_URL}/organizations").mock(
            return_value=httpx.Response(200, json=collection())
        )

        await resolve_party(
            ctx_never_elicit(),
            client,
            search_type="organizations",
            search="Capstone",
        )

        assert route.calls.last.request.url.params["filter[searchTypes][eq]"] == "ORGANIZATION"

    @pytest.mark.asyncio
    @respx.mock
    async def test_people_maps_to_first_and_last_name(self, client: BackstopClient) -> None:
        route = respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=collection())
        )
        respx.get(f"{BASE_URL}/people").mock(return_value=httpx.Response(200, json=collection()))

        await resolve_party(
            ctx_never_elicit(),
            client,
            search_type="people",
            search="Ada Lovelace",
        )

        params = route.calls.last.request.url.params
        assert params["filter[searchTypes][eq]"] == "PERSON_FIRST_NAME,PERSON_LAST_NAME"

    @pytest.mark.asyncio
    @respx.mock
    async def test_contacts_maps_to_first_and_last_name(self, client: BackstopClient) -> None:
        route = respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=collection())
        )
        respx.get(f"{BASE_URL}/contacts").mock(return_value=httpx.Response(200, json=collection()))

        await resolve_party(
            ctx_never_elicit(),
            client,
            search_type="contacts",
            search="Ada Lovelace",
        )

        params = route.calls.last.request.url.params
        assert params["filter[searchTypes][eq]"] == "PERSON_FIRST_NAME,PERSON_LAST_NAME"

    @pytest.mark.asyncio
    @respx.mock
    async def test_employees_maps_to_first_and_last_name(self, client: BackstopClient) -> None:
        route = respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=collection())
        )
        respx.get(f"{BASE_URL}/employees").mock(return_value=httpx.Response(200, json=collection()))

        await resolve_party(
            ctx_never_elicit(),
            client,
            search_type="employees",
            search="Ada Lovelace",
        )

        params = route.calls.last.request.url.params
        assert params["filter[searchTypes][eq]"] == "PERSON_FIRST_NAME,PERSON_LAST_NAME"


class TestPartyIdFromResourceId:
    """UN-23680: quick-search's `id` (e.g. `organizations_341208613`) is not a usable party id —
    the follow-up `GET /organizations/{id}` needs the raw id from `attributes.resourceId`.
    """

    @pytest.mark.asyncio
    @respx.mock
    async def test_prefers_resource_id_attribute_over_prefixed_id(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json=collection(
                    resource(
                        "organizations_341208613",
                        "organizations",
                        name="Capstone",
                        resourceId="341208613",
                    )
                ),
            )
        )

        result = await resolve_party(
            ctx_never_elicit(),
            client,
            search_type="organizations",
            search="Capstone",
        )

        assert isinstance(result, Resolved)
        assert result.value.id == "341208613"

    @pytest.mark.asyncio
    @respx.mock
    async def test_falls_back_to_stripping_type_prefix_when_resource_id_is_absent(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json=collection(
                    resource("organizations_341208613", "organizations", name="Capstone")
                ),
            )
        )

        result = await resolve_party(
            ctx_never_elicit(),
            client,
            search_type="organizations",
            search="Capstone",
        )

        assert isinstance(result, Resolved)
        assert result.value.id == "341208613"

    @pytest.mark.asyncio
    @respx.mock
    async def test_id_without_type_prefix_is_used_as_is_when_resource_id_is_absent(
        self, client: BackstopClient
    ) -> None:
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
        assert result.value.id == "o1"

    @pytest.mark.asyncio
    @respx.mock
    async def test_falls_back_to_stripping_type_prefix_when_resource_id_is_blank(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json=collection(
                    resource(
                        "organizations_341208613",
                        "organizations",
                        name="Capstone",
                        resourceId="   ",
                    )
                ),
            )
        )

        result = await resolve_party(
            ctx_never_elicit(),
            client,
            search_type="organizations",
            search="Capstone",
        )

        assert isinstance(result, Resolved)
        assert result.value.id == "341208613"


class TestHitCounts:
    @pytest.mark.asyncio
    @respx.mock
    async def test_zero_hits_returns_not_found(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=collection())
        )
        respx.get(f"{BASE_URL}/organizations").mock(
            return_value=httpx.Response(200, json=collection())
        )

        result = await resolve_party(
            ctx_never_elicit(),
            client,
            search_type="organizations",
            search="Unknown Co",
        )

        assert isinstance(result, NotFound)
        assert result.query == "Unknown Co"
        assert result.scope == "organizations"

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
        assert result.value.id == "o1"
        assert result.value.name == "Capstone"

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

        assert isinstance(result, Ambiguous)
        assert len(result.candidates) == 2
        assert result.query == "Capstone"


class TestLikeFallback:
    @pytest.mark.asyncio
    @respx.mock
    async def test_empty_quick_search_falls_back_to_organization_name_like(
        self, client: BackstopClient
    ) -> None:
        quick = respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=collection())
        )
        like = respx.get(f"{BASE_URL}/organizations").mock(
            return_value=httpx.Response(
                200,
                json=collection(
                    resource("o1", "organizations", name="Capstone Investment Advisors")
                ),
            )
        )

        result = await resolve_party(
            ctx_never_elicit(),
            client,
            search_type="organizations",
            search="Investment Advisors",
        )

        assert isinstance(result, Resolved)
        assert result.value.id == "o1"
        assert quick.call_count == 1
        assert like.call_count == 1
        params = like.calls.last.request.url.params
        assert params["filter[name][like]"] == "Investment Advisors"
        assert params["page[limit]"] == "200"
        assert "filter[lastName][like]" not in params
        # Without this an organizations row drags `regularCustomFieldValues`: 36x the bytes,
        # for four fields the candidate projection reads.
        assert params["fields[organizations]"] == "name"

    @pytest.mark.asyncio
    @respx.mock
    async def test_empty_quick_search_falls_back_to_people_last_name_like(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=collection())
        )
        like = respx.get(f"{BASE_URL}/people").mock(
            return_value=httpx.Response(
                200,
                json=collection(resource("p1", "people", name="Glenn, Phil", lastName="Glenn")),
            )
        )

        result = await resolve_party(
            ctx_never_elicit(),
            client,
            search_type="people",
            search="Glenn",
        )

        assert isinstance(result, Resolved)
        assert result.value.id == "p1"
        params = like.calls.last.request.url.params
        assert params["filter[lastName][like]"] == "Glenn"
        assert "filter[name][like]" not in params
        assert params["page[limit]"] == "200"
        assert params["fields[people]"] == "name,firstName,lastName"

    @pytest.mark.asyncio
    @respx.mock
    async def test_quick_search_hit_does_not_send_like(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json=collection(resource("o1", "organizations", name="Capstone")),
            )
        )
        like = respx.get(f"{BASE_URL}/organizations").mock(
            return_value=httpx.Response(200, json=collection())
        )

        result = await resolve_party(
            ctx_never_elicit(),
            client,
            search_type="organizations",
            search="Capstone",
        )

        assert isinstance(result, Resolved)
        assert like.call_count == 0


class TestBatchResolve:
    @pytest.mark.asyncio
    @respx.mock
    async def test_batch_returns_one_payload_and_never_elicits(
        self, client: BackstopClient
    ) -> None:
        # Matched on the search text rather than call order: items resolve concurrently, so
        # `side_effect` ordering would be an assumption about scheduling.
        respx.get(f"{BASE_URL}/quick-search", params={"filter[searchText][eq]": "Missing Co"}).mock(
            return_value=httpx.Response(200, json=collection())
        )
        respx.get(f"{BASE_URL}/organizations", params={"filter[name][like]": "Missing Co"}).mock(
            return_value=httpx.Response(200, json=collection())
        )
        respx.get(f"{BASE_URL}/quick-search", params={"filter[searchText][eq]": "Alpha"}).mock(
            return_value=httpx.Response(
                200,
                json=collection(
                    resource("o2", "organizations", name="Alpha"),
                    resource("o3", "organizations", name="Alpha Holdings"),
                ),
            )
        )

        result = await resolve_parties(
            client,
            search_type="organizations",
            items=[
                PartyResolveItemDto(party_id="trusted-1", name="Trusted Org"),
                PartyResolveItemDto(search="Missing Co"),
                PartyResolveItemDto(search="Alpha"),
            ],
        )

        assert isinstance(result, BatchAmbiguous)
        assert len(result.resolved) == 1
        assert result.resolved[0].index == 0
        assert result.resolved[0].value.id == "trusted-1"
        assert result.resolved[0].value.name == "Trusted Org"
        assert len(result.unresolved) == 2
        assert result.unresolved[0].index == 1
        assert result.unresolved[0].candidates == ()
        assert result.unresolved[1].index == 2
        assert len(result.unresolved[1].candidates) == 2

        response = unresolved_parties_response(result)
        assert [item.index for item in response.resolved] == [0]
        assert response.resolved[0].value.id == "trusted-1"
        assert response.resolved[0].value.name == "Trusted Org"
        assert [item.index for item in response.unresolved] == [1, 2]

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
            client,
            search_type="organizations",
            items=[
                PartyResolveItemDto(party_id="trusted-1"),
                PartyResolveItemDto(search="Solo"),
            ],
        )

        assert isinstance(result, BatchResolved)
        assert [party.id for party in result.values] == ["trusted-1", "o1"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_items_resolve_concurrently(self, client: BackstopClient) -> None:
        """A batch is the fan-out case the concurrency gate exists for — it should fan out."""
        release = asyncio.Event()
        in_flight = 0
        max_in_flight = 0

        async def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal in_flight, max_in_flight
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await release.wait()
            in_flight -= 1
            return httpx.Response(200, json=collection())

        respx.get(f"{BASE_URL}/quick-search").mock(side_effect=handler)
        respx.get(f"{BASE_URL}/organizations").mock(
            return_value=httpx.Response(200, json=collection())
        )

        async def run() -> object:
            return await resolve_parties(
                client,
                search_type="organizations",
                items=[PartyResolveItemDto(search=f"Co {i}") for i in range(3)],
            )

        task = asyncio.create_task(run())
        await asyncio.sleep(0.05)
        assert max_in_flight == 3

        release.set()
        await task

    @pytest.mark.asyncio
    @respx.mock
    async def test_batch_response_maps_to_one_structured_payload(
        self, client: BackstopClient
    ) -> None:
        """UN-23676: one combined payload, so the model asks once for the whole batch."""
        respx.get(f"{BASE_URL}/quick-search", params={"filter[searchText][eq]": "Nope"}).mock(
            return_value=httpx.Response(200, json=collection())
        )
        respx.get(f"{BASE_URL}/organizations", params={"filter[name][like]": "Nope"}).mock(
            return_value=httpx.Response(200, json=collection())
        )
        respx.get(f"{BASE_URL}/quick-search", params={"filter[searchText][eq]": "Alpha"}).mock(
            return_value=httpx.Response(
                200,
                json=collection(
                    resource("o2", "organizations", name="Alpha"),
                    resource("o3", "organizations", name="Alpha Holdings"),
                ),
            )
        )

        result = await resolve_parties(
            client,
            search_type="organizations",
            items=[PartyResolveItemDto(search="Nope"), PartyResolveItemDto(search="Alpha")],
        )
        assert isinstance(result, BatchAmbiguous)

        response = unresolved_parties_response(result)

        assert [item.index for item in response.unresolved] == [0, 1]
        assert response.unresolved[0].query == "Nope"
        assert response.unresolved[0].candidates == []
        assert [c.id for c in response.unresolved[1].candidates] == ["o2", "o3"]
        assert [c.search_type for c in response.unresolved[1].candidates] == [
            "organizations",
            "organizations",
        ]
        assert response.unresolved[1].scope == "organizations"
        assert response.resolved == []


class TestConfirmName:
    """Every successful resolution must echo the resolved name + Party ID (UN-23676)."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_confirm_name_fetches_the_name_for_a_trusted_id(
        self, client: BackstopClient
    ) -> None:
        route = respx.get(f"{BASE_URL}/organizations/org-7").mock(
            return_value=httpx.Response(
                200, json={"data": resource("org-7", "organizations", name="Capstone LP")}
            )
        )

        result = await resolve_party(
            ctx_never_elicit(),
            client,
            search_type="organizations",
            party_id="org-7",
            confirm_name=True,
        )

        assert isinstance(result, Resolved)
        assert result.value.name == "Capstone LP"
        assert route.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_confirm_name_is_skipped_when_the_name_is_already_known(
        self, client: BackstopClient
    ) -> None:
        result = await resolve_party(
            ctx_never_elicit(),
            client,
            search_type="organizations",
            party_id="org-7",
            name="Already Known",
            confirm_name=True,
        )

        assert isinstance(result, Resolved)
        assert result.value.name == "Already Known"
        assert len(respx.calls) == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_confirm_name_fetches_when_name_is_blank(self, client: BackstopClient) -> None:
        route = respx.get(f"{BASE_URL}/organizations/org-7").mock(
            return_value=httpx.Response(
                200, json={"data": resource("org-7", "organizations", name="Capstone LP")}
            )
        )

        result = await resolve_party(
            ctx_never_elicit(),
            client,
            search_type="organizations",
            party_id="org-7",
            name="   ",
            confirm_name=True,
        )

        assert isinstance(result, Resolved)
        assert result.value.name == "Capstone LP"
        assert route.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_default_leaves_the_trusted_id_path_request_free(
        self, client: BackstopClient
    ) -> None:
        """Callers that fetch the record anyway shouldn't pay for a second request."""
        result = await resolve_party(
            ctx_never_elicit(),
            client,
            search_type="organizations",
            party_id="org-7",
        )

        assert isinstance(result, Resolved)
        assert result.value.name is None
        assert len(respx.calls) == 0


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
            PartyResolveItemDto(party_id="o1", search="Capstone")

    def test_party_resolve_item_rejects_neither(self) -> None:
        with pytest.raises(ValueError, match="Exactly one of party_id or search"):
            PartyResolveItemDto()

    def test_party_resolve_item_treats_blank_selectors_as_unset(self) -> None:
        item = PartyResolveItemDto(party_id="  ", search="Capstone")
        assert item.party_id is None
        assert item.search == "Capstone"

        item = PartyResolveItemDto(party_id="o1", search="")
        assert item.party_id == "o1"
        assert item.search is None

    def test_party_resolve_item_treats_blank_name_as_unset(self) -> None:
        item = PartyResolveItemDto(party_id="o1", name="   ")
        assert item.name is None
        item = PartyResolveItemDto(party_id="o1", name="")
        assert item.name is None
        item = PartyResolveItemDto(party_id="o1", name=" Capstone ")
        assert item.name == "Capstone"


def _two_org_hits() -> dict[str, object]:
    return collection(
        resource("o1", "organizations", name="Capstone A"),
        resource("o2", "organizations", name="Capstone B"),
    )


def _candidate(party_id: str, label: str) -> Candidate[ResolvedPartyDto]:
    return Candidate(
        key=party_id,
        label=label,
        value=ResolvedPartyDto(id=party_id, search_type="organizations", name=label),
    )


def _ambiguous(*candidates: Candidate[ResolvedPartyDto]) -> Ambiguous[ResolvedPartyDto]:
    return Ambiguous(query="Capstone", scope="organizations", candidates=candidates)


class TestElicitChoice:
    """Both resolvers share one ambiguity policy, so it is tested once, on `elicit_choice`."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_elicit_accept_resolves_selected_candidate(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=_two_org_hits())
        )

        result = await resolve_party(
            ctx_accept("Capstone B (organization)"),
            client,
            search_type="organizations",
            search="Capstone",
        )

        assert isinstance(result, Resolved)
        assert result.value.id == "o2"
        assert result.value.name == "Capstone B"

    @pytest.mark.asyncio
    @respx.mock
    async def test_elicit_decline_returns_ambiguous(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=_two_org_hits())
        )

        result = await resolve_party(
            ctx_decline(),
            client,
            search_type="organizations",
            search="Capstone",
        )

        assert isinstance(result, Ambiguous)
        assert [c.value.id for c in result.candidates] == ["o1", "o2"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_elicit_cancel_returns_ambiguous(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=_two_org_hits())
        )

        result = await resolve_party(
            ctx_cancel(),
            client,
            search_type="organizations",
            search="Capstone",
        )

        assert isinstance(result, Ambiguous)
        assert len(result.candidates) == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_elicit_raising_returns_ambiguous(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=_two_org_hits())
        )

        result = await resolve_party(
            ctx_unsupported(),
            client,
            search_type="organizations",
            search="Capstone",
        )

        assert isinstance(result, Ambiguous)
        assert result.query == "Capstone"
        assert result.scope == "organizations"

    @pytest.mark.asyncio
    async def test_elicit_method_not_found_returns_ambiguous(self) -> None:
        elicit_calls = 0

        async def elicit(*, message: str, response_type: object) -> object:
            nonlocal elicit_calls
            elicit_calls += 1
            _ = message, response_type
            raise McpError(ErrorData(code=METHOD_NOT_FOUND, message="Method not found"))

        ambiguous = _ambiguous(_candidate("o1", "A"), _candidate("o2", "B"))
        result = await elicit_choice(
            as_context(FakeContext(elicit)), ambiguous, prompt="Which one?"
        )

        assert result is ambiguous
        assert elicit_calls == 1

    @pytest.mark.asyncio
    async def test_missing_elicitation_capability_skips_elicit(self) -> None:
        ambiguous = _ambiguous(_candidate("o1", "A"), _candidate("o2", "B"))

        result = await elicit_choice(
            ctx_no_elicitation_capability(), ambiguous, prompt="Which one?"
        )

        assert result is ambiguous

    @pytest.mark.asyncio
    async def test_capability_check_error_degrades_rather_than_guessing(self) -> None:
        async def elicit(*, message: str, response_type: object) -> AcceptedElicitation[str]:
            _ = message, response_type
            raise AssertionError("elicit must not be attempted")

        class _BrokenSession:
            def check_client_capability(self, capability: ClientCapabilities) -> bool:
                _ = capability
                raise RuntimeError("client session is in a weird state")

        fake = FakeContext(elicit)
        object.__setattr__(fake.request_context, "session", _BrokenSession())

        ambiguous = _ambiguous(_candidate("o1", "A"), _candidate("o2", "B"))
        result = await elicit_choice(as_context(fake), ambiguous, prompt="Which one?")

        assert result is ambiguous

    @pytest.mark.asyncio
    async def test_no_request_context_degrades(self) -> None:
        class _ContextlessContext:
            request_context: None = None

            async def elicit(self, *, message: str, response_type: object) -> object:
                _ = message, response_type
                raise AssertionError("elicit must not be attempted")

        ambiguous = _ambiguous(_candidate("o1", "A"), _candidate("o2", "B"))
        result = await elicit_choice(
            as_context(_ContextlessContext()),  # pyright: ignore[reportArgumentType]
            ambiguous,
            prompt="Which one?",
        )

        assert result is ambiguous

    @pytest.mark.skip(
        reason="Manual spike: Unique MCP client elicit interop (UN-23676); not runnable in CI"
    )
    def test_unique_client_elicit_interop_spike(self) -> None:
        """Manual: against Unique chat client, ambiguous get_organization search should either
        elicit an enum or degrade to `ambiguous` candidates — never crash the tool.
        """

    @pytest.mark.asyncio
    async def test_duplicate_labels_are_made_unique_for_elicit(self) -> None:
        captured: dict[str, object] = {}

        async def elicit(*, message: str, response_type: object) -> AcceptedElicitation[str]:
            captured["message"] = message
            captured["response_type"] = response_type
            return AcceptedElicitation(data="Acme [o2]")

        ambiguous = _ambiguous(_candidate("o1", "Acme"), _candidate("o2", "Acme"))
        result = await elicit_choice(
            as_context(FakeContext(elicit)), ambiguous, prompt="Which Acme?"
        )

        assert isinstance(result, Resolved)
        assert result.value.id == "o2"
        assert captured["response_type"] == ["Acme [o1]", "Acme [o2]"]
        assert captured["message"] == "Which Acme?"

    @pytest.mark.asyncio
    async def test_unrecognized_choice_degrades(self) -> None:
        async def elicit(*, message: str, response_type: object) -> AcceptedElicitation[str]:
            _ = message, response_type
            return AcceptedElicitation(data="Something Else Entirely")

        ambiguous = _ambiguous(_candidate("o1", "A"), _candidate("o2", "B"))
        result = await elicit_choice(
            as_context(FakeContext(elicit)), ambiguous, prompt="Which one?"
        )

        assert result is ambiguous
