from collections.abc import Callable

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopResponseSchemaError
from backstop_mcp.features.data_hygiene import AsOf
from backstop_mcp.features.includes import InternalOwnerResponse
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
from tests.server.tools.helpers import object_dict, tool_model, tool_model_union, tool_payload

type ConnectUser = Callable[..., object]


def _organization_document(
    *,
    attributes: dict[str, object] | None = None,
    relationships: dict[str, object] | None = None,
    included: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "data": {
            "type": "organizations",
            "id": "o42",
            "attributes": attributes
            or {
                "name": "Koch Investments Group",
                "modifiedTimestamp": "2025-03-01T10:00:00Z",
                "modifiedBy": "ops",
            },
            "relationships": relationships or {},
        },
        "included": included or [],
    }


def _location(resource_id: str, title: str, *, primary: bool) -> dict[str, object]:
    """A `contact-locations` resource with every attribute the live API sends."""
    return {
        "type": "contact-locations",
        "id": resource_id,
        "attributes": {
            "locationTitle": title,
            "address": "18867 North Thompson Peak Parkway, Suite 250",
            "city": "Scottsdale",
            "cityResolvedName": "Scottsdale",
            "state": "AZ",
            "stateResolvedName": "AZ",
            "country": "United States of America",
            "countryResolvedName": "United States of America",
            "countryCode": "US",
            "postalCode": "85255",
            "phoneNumber": "(480) 419-3625",
            "secondaryPhoneNumber": "",
            "fax": "",
            "isPrimaryLocation": primary,
            "primaryLocation": primary,
            "createdTimestamp": "2019-04-02T14:21:00Z",
            "modifiedTimestamp": "2024-11-18T09:05:00Z",
        },
    }


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
        # `model_validate`, not kwargs: `status` is an `extra="allow"` passthrough and the
        # provenance fields bind by alias, neither of which the synthesized `__init__` knows.
        assert result.organization == OrganizationAttributes.model_validate(
            {
                "name": "Capstone",
                "status": "active",
                "modified_timestamp": "2025-03-01T10:00:00Z",
                "modified_by": "ops",
            }
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
                PartyCandidateResponse(
                    key="organizations:o1",
                    label="Capstone A",
                    id="o1",
                    search_type="organizations",
                    name="Capstone A",
                ),
                PartyCandidateResponse(
                    key="organizations:o2",
                    label="Capstone B",
                    id="o2",
                    search_type="organizations",
                    name="Capstone B",
                ),
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

    @pytest.mark.asyncio
    @respx.mock
    async def test_does_not_declare_glossary_meta(self, connect_user: ConnectUser) -> None:
        await connect_user("user-org-glossary", "org-glossary")  # pyright: ignore[reportGeneralTypeIssues]

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

        assert "glossary_meta" not in OrganizationResolvedResponse.model_fields
        assert "glossary_meta" not in result.model_dump()
        assert "glossary_meta" not in (get_organization.__doc__ or "")


class TestGetOrganizationIncludes:
    @pytest.mark.asyncio
    @respx.mock
    async def test_locations_carry_their_title_and_primary_flag(
        self, connect_user: ConnectUser
    ) -> None:
        """And Backstop's duplicate source fields collapse to one projected field each."""
        await connect_user("user-org-includes-1", "org-includes-locations")  # pyright: ignore[reportGeneralTypeIssues]

        org_get = respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(
                200,
                json=_organization_document(
                    relationships={
                        "contactLocations": {
                            "data": [
                                {"type": "contact-locations", "id": "loc-1"},
                                {"type": "contact-locations", "id": "loc-2"},
                            ]
                        }
                    },
                    included=[
                        _location("loc-1", "Business", primary=True),
                        _location("loc-2", "Home", primary=False),
                    ],
                ),
            )
        )

        result = tool_model(
            await get_organization(ctx_never_elicit(), party_id="o42", include=["locations"]),
            OrganizationResolvedResponse,
        )

        assert org_get.calls.last.request.url.params["include"] == "contactLocations"
        included = result.included
        assert included is not None
        locations = included.locations
        assert locations is not None
        assert [(one.location_title, one.is_primary) for one in locations] == [
            ("Business", True),
            ("Home", False),
        ]
        assert locations[0].model_dump() == {
            "location_title": "Business",
            "address": "18867 North Thompson Peak Parkway, Suite 250",
            "city": "Scottsdale",
            "state": "AZ",
            "country": "United States of America",
            "postal_code": "85255",
            "phone": "(480) 419-3625",
            "is_primary": True,
        }

    @pytest.mark.asyncio
    @respx.mock
    async def test_an_address_book_with_nothing_in_it_is_empty_not_absent(
        self, connect_user: ConnectUser
    ) -> None:
        """`[]` is "we looked, there are none"; the names not asked for are absent entirely."""
        await connect_user("user-org-includes-2", "org-includes-no-emails")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(
                200, json=_organization_document(relationships={"contactEmails": {"data": []}})
            )
        )

        payload = tool_payload(
            await get_organization(ctx_never_elicit(), party_id="o42", include=["email_addresses"])
        )

        assert object_dict(payload["included"]) == {"email_addresses": []}

    @pytest.mark.asyncio
    @respx.mock
    async def test_the_primary_contact_is_trimmed_to_a_contact_card(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-org-includes-3", "org-includes-primary-contact")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(
                200,
                json=_organization_document(
                    relationships={"primaryContact": {"data": {"type": "people", "id": "p1"}}},
                    included=[
                        {
                            "type": "people",
                            "id": "p1",
                            "attributes": {
                                "name": "Voss, Kent",
                                "firstName": "Kent",
                                "lastName": "Voss",
                                "jobTitle": "Managing Director, Research",
                                "email": "vossk@kochinvests.com",
                                "phone": "(480) 419-3625",
                                "companyName": "Koch Investments Group",
                                "companyId": 341208613,
                                "streetAddress": "18867 North Thompson Peak Parkway",
                                "city": "Scottsdale",
                                "state": "AZ",
                                "postalCode": "85255",
                                "country": "United States of America",
                                "salutation": "Mr.",
                                "fax": "",
                                "mobilePhone": "",
                                "assistantName": "",
                                "createdTimestamp": "2019-04-02T14:21:00Z",
                                "modifiedTimestamp": "2024-11-18T09:05:00Z",
                                "modifiedBy": "ops",
                                "regularCustomFieldValues": {"1": "noise"},
                            },
                        }
                    ],
                ),
            )
        )

        result = tool_model(
            await get_organization(ctx_never_elicit(), party_id="o42", include=["primary_contact"]),
            OrganizationResolvedResponse,
        )

        included = result.included
        assert included is not None
        card = included.primary_contact
        assert card is not None
        assert card.model_dump() == {
            "name": "Voss, Kent",
            "job_title": "Managing Director, Research",
            "email": "vossk@kochinvests.com",
            "phone": "(480) 419-3625",
            "company_name": "Koch Investments Group",
        }

    @pytest.mark.asyncio
    @respx.mock
    async def test_the_representative_is_documented_as_our_own_colleague(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-org-includes-4", "org-includes-representative")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(
                200,
                json=_organization_document(
                    relationships={
                        "representative": {"data": {"type": "system-users", "id": "u1"}}
                    },
                    included=[
                        {
                            "type": "system-users",
                            "id": "u1",
                            "attributes": {
                                "name": "Margaret Lucas",
                                "fullName": "Margaret Lucas",
                                "firstName": "Margaret",
                                "lastName": "Lucas",
                                "userName": "mlucas",
                                "email": "margaret.lucas@capstoneco.com",
                                "phoneNumber": "12122321462",
                                "timeZone": "America/New_York",
                                "dateFormat": "MM/dd/yyyy",
                                "targetCurrency": "USD",
                                "enabledUserFeatures": [],
                                "disabled": False,
                                "isBsgAdmin": False,
                            },
                        }
                    ],
                ),
            )
        )

        result = tool_model(
            await get_organization(ctx_never_elicit(), party_id="o42", include=["representative"]),
            OrganizationResolvedResponse,
        )

        included = result.included
        assert included is not None
        owner = included.representative
        assert isinstance(owner, InternalOwnerResponse)
        assert owner.model_dump() == {
            "name": "Margaret Lucas",
            "user_name": "mlucas",
            "email": "margaret.lucas@capstoneco.com",
            "phone": "12122321462",
        }
        # The tool has to say this reaches our own office, not the organization.
        assert "not a way to contact the organization" in (get_organization.__doc__ or "")

    @pytest.mark.asyncio
    @respx.mock
    async def test_omitting_include_leaves_no_included_key_and_no_include_param(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-org-includes-5", "org-includes-none")  # pyright: ignore[reportGeneralTypeIssues]

        org_get = respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(200, json=_organization_document())
        )

        payload = tool_payload(await get_organization(ctx_never_elicit(), party_id="o42"))

        assert "included" not in payload
        assert "include" not in org_get.calls.last.request.url.params

    @pytest.mark.asyncio
    @respx.mock
    async def test_all_four_includes_travel_as_one_query_value(
        self, connect_user: ConnectUser
    ) -> None:
        """Measured live: Backstop takes the whole set on one GET, comma-separated."""
        await connect_user("user-org-includes-6", "org-includes-all")  # pyright: ignore[reportGeneralTypeIssues]

        org_get = respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(200, json=_organization_document())
        )

        payload = tool_payload(
            await get_organization(
                ctx_never_elicit(),
                party_id="o42",
                include=["locations", "email_addresses", "primary_contact", "representative"],
            )
        )

        assert org_get.calls.last.request.url.params["include"] == (
            "contactLocations,contactEmails,primaryContact,representative"
        )
        # The two lists say "we looked, there are none"; the two to-ones have nothing to say.
        assert object_dict(payload["included"]) == {"locations": [], "email_addresses": []}

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_lone_to_one_that_resolves_to_nothing_leaves_included_empty(
        self, connect_user: ConnectUser
    ) -> None:
        """`included: {}` is the answer, not an absent key: we did look, nobody is assigned."""
        await connect_user("user-org-includes-7", "org-includes-empty-to-one")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(
                200,
                json=_organization_document(relationships={"primaryContact": {"data": None}}),
            )
        )

        payload = tool_payload(
            await get_organization(ctx_never_elicit(), party_id="o42", include=["primary_contact"])
        )

        assert object_dict(payload["included"]) == {}


class TestGetOrganizationOmitsNullsFromTheWire:
    """The payload carries no nulls at all: an absent key means "no value", not "we did not look".

    Asserted on the raw payload, because `tool_model` reads absent and null identically and would
    not notice this behaviour changing in either direction.
    """

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_null_backstop_attribute_is_not_a_key_but_a_filled_one_is(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-org-nulls-1", "org-null-attribute")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(
                200,
                json=_organization_document(
                    attributes={
                        "name": "Koch Investments Group",
                        "website": None,
                        "modifiedTimestamp": "2025-03-01T10:00:00Z",
                        "modifiedBy": "ops",
                    }
                ),
            )
        )

        payload = tool_payload(await get_organization(ctx_never_elicit(), party_id="o42"))

        organization = object_dict(payload["organization"])
        assert "website" not in organization
        assert organization["name"] == "Koch Investments Group"

    @pytest.mark.asyncio
    @respx.mock
    async def test_custom_field_values_survive_intact(self, connect_user: ConnectUser) -> None:
        """A plain dict, not a model, so nothing prunes it — write-back still round-trips."""
        await connect_user("user-org-nulls-2", "org-custom-fields")  # pyright: ignore[reportGeneralTypeIssues]

        custom_fields = [
            {"definitionId": 343439, "name": "Status", "value": "Attended - Web & Adio"}
        ]
        respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(
                200,
                json=_organization_document(
                    attributes={
                        "name": "Koch Investments Group",
                        "regularCustomFieldValues": custom_fields,
                        "modifiedTimestamp": "2025-03-01T10:00:00Z",
                        "modifiedBy": "ops",
                    }
                ),
            )
        )

        payload = tool_payload(await get_organization(ctx_never_elicit(), party_id="o42"))

        assert object_dict(payload["organization"])["regularCustomFieldValues"] == custom_fields

    @pytest.mark.asyncio
    @respx.mock
    async def test_as_of_is_absent_when_backstop_records_no_provenance(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-org-nulls-3", "org-no-provenance")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(
                200,
                json=_organization_document(attributes={"name": "Koch Investments Group"}),
            )
        )

        payload = tool_payload(await get_organization(ctx_never_elicit(), party_id="o42"))

        assert "as_of" not in payload
