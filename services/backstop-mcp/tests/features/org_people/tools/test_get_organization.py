from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient, BackstopResponseSchemaError
from backstop_mcp.features.custom_fields import CustomFieldsService
from backstop_mcp.features.data_hygiene import AsOfResponse
from backstop_mcp.features.includes import InternalOwnerResponse
from backstop_mcp.features.org_people import (
    OrganizationRecordResponse,
    OrganizationResolvedResponse,
)
from backstop_mcp.features.org_people.tools.get_organization import (
    GetOrganizationResponse,
    get_organization,
)
from backstop_mcp.features.party_resolver import (
    PartyAmbiguousResponse,
    PartyCandidateResponse,
    ResolvedPartyResponse,
)
from backstop_mcp.features.resolution import NotFoundResponse
from backstop_mcp.models import CoercedId
from tests.features.org_people.conftest import make_get_organization_query
from tests.features.party_resolver.helpers import (
    BASE_URL,
    collection,
    ctx_decline,
    ctx_never_elicit,
    resource,
)
from tests.helpers import custom_fields_service, recorded_requests
from tests.server.tools.helpers import (
    object_dict,
    object_list,
    tool_model,
    tool_model_union,
    tool_payload,
)

_EMPTY_DEFINITIONS: dict[str, object] = {"data": [], "links": {"next": None}}


@pytest.fixture(autouse=True)
def _empty_custom_field_definitions() -> None:
    respx.get(f"{BASE_URL}/custom-field-definitions").mock(
        return_value=httpx.Response(200, json=_EMPTY_DEFINITIONS)
    )


def _catalog(client: BackstopClient) -> CustomFieldsService:
    return custom_fields_service(client)


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
        self, client: BackstopClient
    ) -> None:

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
            await get_organization(
                ctx_never_elicit(),
                search="Capstone",
                client=client,
                get_organization_query=make_get_organization_query(
                    client, custom_fields=_catalog(client)
                ),
            ),
            OrganizationResolvedResponse,
        )

        # `organization` is the record's own fields, not the enclosing JSON:API document —
        # `type`/`id` are already echoed under `resolved`.
        # `model_validate`, not kwargs: `status` is an `extra="allow"` passthrough and the
        # provenance fields bind by alias, neither of which the synthesized `__init__` knows.
        assert result.organization == OrganizationRecordResponse.model_validate(
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
        assert result.as_of == AsOfResponse(
            modified_timestamp="2025-03-01T10:00:00Z", modified_by="ops"
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_ambiguous_search_returns_candidates_without_org_get(
        self, client: BackstopClient
    ) -> None:

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
            await get_organization(
                ctx_decline(),
                search="Capstone",
                client=client,
                get_organization_query=make_get_organization_query(
                    client, custom_fields=_catalog(client)
                ),
            ),
            PartyAmbiguousResponse,
        )

        assert result == PartyAmbiguousResponse(
            query="Capstone",
            scope="organizations",
            candidates=[
                PartyCandidateResponse(
                    key="organizations:o1",
                    label="Capstone A (organization)",
                    id="o1",
                    search_type="organizations",
                    name="Capstone A",
                ),
                PartyCandidateResponse(
                    key="organizations:o2",
                    label="Capstone B (organization)",
                    id="o2",
                    search_type="organizations",
                    name="Capstone B",
                ),
            ],
        )
        assert org_get.call_count == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_trusted_party_id_fetches_organization(self, client: BackstopClient) -> None:

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
            await get_organization(
                ctx_never_elicit(),
                party_id="trusted-9",
                search_type="organizations",
                client=client,
                get_organization_query=make_get_organization_query(
                    client, custom_fields=_catalog(client)
                ),
            ),
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
        self, client: BackstopClient
    ) -> None:
        # Defense in depth alongside the '/' rejection in resolve_party.py: any character that
        # could otherwise change the request's structure (here, a space) must be encoded
        # rather than interpolated raw into the path.

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
            await get_organization(
                ctx_never_elicit(),
                party_id="trusted 9",
                client=client,
                get_organization_query=make_get_organization_query(
                    client, custom_fields=_catalog(client)
                ),
            ),
            OrganizationResolvedResponse,
        )

        assert isinstance(result, OrganizationResolvedResponse)
        assert org_get.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_trusted_party_id_containing_slash_is_rejected(
        self, client: BackstopClient
    ) -> None:

        with pytest.raises(ValueError, match="must not contain '/'"):
            await get_organization(
                ctx_never_elicit(),
                party_id="../admin",
                client=client,
                get_organization_query=make_get_organization_query(
                    client, custom_fields=_catalog(client)
                ),
            )

    @pytest.mark.asyncio
    @respx.mock
    async def test_malformed_organization_body_raises_schema_error(
        self, client: BackstopClient
    ) -> None:

        # `id` is entirely absent from the organization resource — fails
        # `BackstopApiResourceDocument[OrganizationRecordResponse]` schema validation outright.
        respx.get(f"{BASE_URL}/organizations/trusted-9").mock(
            return_value=httpx.Response(
                200,
                json={"data": {"type": "organizations", "attributes": {"name": "From Body"}}},
            )
        )

        with pytest.raises(BackstopResponseSchemaError) as exc_info:
            await get_organization(
                ctx_never_elicit(),
                party_id="trusted-9",
                client=client,
                get_organization_query=make_get_organization_query(
                    client, custom_fields=_catalog(client)
                ),
            )

        assert exc_info.value.path == "/organizations/trusted-9"
        assert exc_info.value.schema_name == ("BackstopApiResourceDocument[OrganizationAttributes]")

    @pytest.mark.asyncio
    @respx.mock
    async def test_not_found_search_returns_the_query_it_used(self, client: BackstopClient) -> None:
        """Policy step 5: name the exact term searched for, so a typo is correctable."""

        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=collection())
        )
        respx.get(f"{BASE_URL}/organizations").mock(
            return_value=httpx.Response(200, json=collection())
        )

        result = tool_model_union(
            await get_organization(
                ctx_never_elicit(),
                search="Capstoen",
                client=client,
                get_organization_query=make_get_organization_query(
                    client, custom_fields=_catalog(client)
                ),
            ),
            GetOrganizationResponse,
        )

        assert isinstance(result, NotFoundResponse)
        assert result.status == "not_found"
        assert getattr(result, "query", None) == "Capstoen"
        assert getattr(result, "scope", None) == "organizations"

    @pytest.mark.asyncio
    @respx.mock
    async def test_does_not_declare_glossary_meta(self, client: BackstopClient) -> None:

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
            await get_organization(
                ctx_never_elicit(),
                search="Capstone",
                client=client,
                get_organization_query=make_get_organization_query(
                    client, custom_fields=_catalog(client)
                ),
            ),
            OrganizationResolvedResponse,
        )

        assert "glossary_meta" not in OrganizationResolvedResponse.model_fields
        assert "glossary_meta" not in result.model_dump()
        assert "glossary_meta" not in (get_organization.__doc__ or "")


class TestGetOrganizationIncludes:
    @pytest.mark.asyncio
    @respx.mock
    async def test_locations_carry_their_title_and_primary_flag(
        self, client: BackstopClient
    ) -> None:
        """And Backstop's duplicate source fields collapse to one projected field each."""

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
            await get_organization(
                ctx_never_elicit(),
                party_id="o42",
                include=["locations"],
                client=client,
                get_organization_query=make_get_organization_query(
                    client, custom_fields=_catalog(client)
                ),
            ),
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
            "id": "loc-1",
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
        self, client: BackstopClient
    ) -> None:
        """`[]` is "we looked, there are none"; the names not asked for are absent entirely."""

        respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(
                200, json=_organization_document(relationships={"contactEmails": {"data": []}})
            )
        )

        payload = tool_payload(
            await get_organization(
                ctx_never_elicit(),
                party_id="o42",
                include=["email_addresses"],
                client=client,
                get_organization_query=make_get_organization_query(
                    client, custom_fields=_catalog(client)
                ),
            )
        )

        assert object_dict(payload["included"]) == {"email_addresses": []}

    @pytest.mark.asyncio
    @respx.mock
    async def test_the_primary_contact_is_trimmed_to_a_contact_card(
        self, client: BackstopClient
    ) -> None:

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
            await get_organization(
                ctx_never_elicit(),
                party_id="o42",
                include=["primary_contact"],
                client=client,
                get_organization_query=make_get_organization_query(
                    client, custom_fields=_catalog(client)
                ),
            ),
            OrganizationResolvedResponse,
        )

        included = result.included
        assert included is not None
        card = included.primary_contact
        assert card is not None
        assert card.model_dump() == {
            "id": "p1",
            "name": "Voss, Kent",
            "job_title": "Managing Director, Research",
            "email": "vossk@kochinvests.com",
            "phone": "(480) 419-3625",
            "company_name": "Koch Investments Group",
        }

    @pytest.mark.asyncio
    @respx.mock
    async def test_the_representative_is_documented_as_our_own_colleague(
        self, client: BackstopClient
    ) -> None:

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
            await get_organization(
                ctx_never_elicit(),
                party_id="o42",
                include=["representative"],
                client=client,
                get_organization_query=make_get_organization_query(
                    client, custom_fields=_catalog(client)
                ),
            ),
            OrganizationResolvedResponse,
        )

        included = result.included
        assert included is not None
        owner = included.representative
        assert isinstance(owner, InternalOwnerResponse)
        assert owner.model_dump() == {
            "id": "u1",
            "name": "Margaret Lucas",
            "user_name": "mlucas",
            "email": "margaret.lucas@capstoneco.com",
            "phone": "12122321462",
            "disabled": False,
        }
        # The tool has to say this reaches our own office, not the organization.
        assert "not a way to contact the organization" in (get_organization.__doc__ or "")

    @pytest.mark.asyncio
    @respx.mock
    async def test_omitting_include_leaves_no_included_key_and_no_include_param(
        self, client: BackstopClient
    ) -> None:

        org_get = respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(200, json=_organization_document())
        )

        payload = tool_payload(
            await get_organization(
                ctx_never_elicit(),
                party_id="o42",
                client=client,
                get_organization_query=make_get_organization_query(
                    client, custom_fields=_catalog(client)
                ),
            )
        )

        assert "included" not in payload
        assert "include" not in org_get.calls.last.request.url.params

    @pytest.mark.asyncio
    @respx.mock
    async def test_all_four_includes_travel_as_one_query_value(
        self, client: BackstopClient
    ) -> None:
        """Measured live: Backstop takes the whole set on one GET, comma-separated."""

        org_get = respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(200, json=_organization_document())
        )

        payload = tool_payload(
            await get_organization(
                ctx_never_elicit(),
                party_id="o42",
                include=["locations", "email_addresses", "primary_contact", "representative"],
                client=client,
                get_organization_query=make_get_organization_query(
                    client, custom_fields=_catalog(client)
                ),
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
        self, client: BackstopClient
    ) -> None:
        """`included: {}` is the answer, not an absent key: we did look, nobody is assigned."""

        respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(
                200,
                json=_organization_document(relationships={"primaryContact": {"data": None}}),
            )
        )

        payload = tool_payload(
            await get_organization(
                ctx_never_elicit(),
                party_id="o42",
                include=["primary_contact"],
                client=client,
                get_organization_query=make_get_organization_query(
                    client, custom_fields=_catalog(client)
                ),
            )
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
        self, client: BackstopClient
    ) -> None:

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

        payload = tool_payload(
            await get_organization(
                ctx_never_elicit(),
                party_id="o42",
                client=client,
                get_organization_query=make_get_organization_query(
                    client, custom_fields=_catalog(client)
                ),
            )
        )

        organization = object_dict(payload["organization"])
        assert "website" not in organization
        assert organization["name"] == "Koch Investments Group"

    @pytest.mark.asyncio
    @respx.mock
    async def test_raw_custom_field_dump_is_absent_from_the_record(
        self, client: BackstopClient
    ) -> None:

        respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(
                200,
                json=_organization_document(
                    attributes={
                        "name": "Koch Investments Group",
                        "regularCustomFieldValues": [
                            {"definitionId": 343439, "name": "Shared Name", "value": "kept"}
                        ],
                        "modifiedTimestamp": "2025-03-01T10:00:00Z",
                        "modifiedBy": "ops",
                    }
                ),
            )
        )

        payload = tool_payload(
            await get_organization(
                ctx_never_elicit(),
                party_id="o42",
                client=client,
                get_organization_query=make_get_organization_query(
                    client, custom_fields=_catalog(client)
                ),
            )
        )

        organization = object_dict(payload["organization"])
        assert "regularCustomFieldValues" not in organization
        assert "regular_custom_field_values" not in organization
        assert object_list(payload["custom_field_values"]) == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_as_of_is_absent_when_backstop_records_no_provenance(
        self, client: BackstopClient
    ) -> None:

        respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(
                200,
                json=_organization_document(attributes={"name": "Koch Investments Group"}),
            )
        )

        payload = tool_payload(
            await get_organization(
                ctx_never_elicit(),
                party_id="o42",
                client=client,
                get_organization_query=make_get_organization_query(
                    client, custom_fields=_catalog(client)
                ),
            )
        )

        assert "as_of" not in payload

    @pytest.mark.asyncio
    @respx.mock
    async def test_resolved_omits_name_when_the_record_has_none(
        self, client: BackstopClient
    ) -> None:

        respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(
                200,
                json=_organization_document(attributes={"status": "active"}),
            )
        )

        payload = tool_payload(
            await get_organization(
                ctx_never_elicit(),
                party_id="o42",
                client=client,
                get_organization_query=make_get_organization_query(
                    client, custom_fields=_catalog(client)
                ),
            )
        )

        resolved = object_dict(payload["resolved"])
        assert resolved["id"] == "o42"
        assert "name" not in resolved


def _definition(
    definition_id: str, *, name: str, entity_type: str, **attrs: object
) -> dict[str, object]:
    return resource(
        definition_id,
        "custom-field-definitions",
        name=name,
        entityType=entity_type,
        **attrs,
    )


def _definitions_route(*definitions: dict[str, object]) -> respx.Route:
    return respx.get(f"{BASE_URL}/custom-field-definitions").mock(
        return_value=httpx.Response(200, json={"data": list(definitions), "links": {"next": None}})
    )


def _org_custom_field_document(values: Sequence[Mapping[str, object]]) -> dict[str, object]:
    return _organization_document(
        attributes={
            "name": "Koch Investments Group",
            "regularCustomFieldValues": values,
            "modifiedTimestamp": "2025-03-01T10:00:00Z",
            "modifiedBy": "ops",
        }
    )


_ORG_BEAN_FIELD = _definition(
    "101",
    name="Org Field",
    entity_type="OrganizationBean",
    fieldType="text",
    tabName="Org Tab",
    groupName="Org Group",
    groupId=11,
    layoutName="Organization Layout",
)
_PARTY_BEAN_FIELD = _definition(
    "202",
    name="Party Field",
    entity_type="PartyBean",
    fieldType="text",
    tabName="Party Tab",
    groupName="Party Group",
    groupId=22,
    layoutName="Party Layout",
)
_SHARED_NAME_ORG = _definition(
    "301",
    name="Shared Name",
    entity_type="OrganizationBean",
    fieldType="text",
    tabName="First Tab",
    groupName="First Group",
    groupId=31,
    layoutName="First Layout",
)
_SHARED_NAME_PARTY = _definition(
    "302",
    name="Shared Name",
    entity_type="PartyBean",
    fieldType="text",
    tabName="Second Tab",
    groupName="Second Group",
    groupId=32,
    layoutName="Second Layout",
)
_PICK_FIELD = _definition(
    "401",
    name="Pick Field",
    entity_type="OrganizationBean",
    fieldType="picklist",
    selectOptions=[{"label": "Listed Option"}, {"label": "Other Option"}],
    tabName="Org Tab",
    groupName="Org Group",
    groupId=11,
    layoutName="Organization Layout",
)
_LISTED_PICK_FIELD = _definition(
    "402",
    name="Listed Pick Field",
    entity_type="OrganizationBean",
    fieldType="picklist",
    selectOptions=[{"label": "Listed Option"}],
    tabName="Org Tab",
    groupName="Org Group",
    groupId=11,
    layoutName="Organization Layout",
)
_ENTITY_PERSON_FIELD = _definition(
    "501",
    name="Related Person",
    entity_type="OrganizationBean",
    fieldType="ENTITY",
    tabName="Org Tab",
    groupName="Org Group",
    groupId=11,
    layoutName="Organization Layout",
)
_ENTITY_ACCOUNT_FIELD = _definition(
    "502",
    name="Related Account",
    entity_type="OrganizationBean",
    fieldType="ENTITY",
    tabName="Org Tab",
    groupName="Org Group",
    groupId=11,
    layoutName="Organization Layout",
)

_ORG_AND_PARTY_VALUES: list[dict[str, object]] = [
    {"definitionId": 101, "name": "Org Field", "value": "org-value"},
    {"definitionId": 202, "name": "Party Field", "value": "party-value"},
]


async def _organization_custom_fields(
    client: BackstopClient,
    catalog: CustomFieldsService,
    *,
    custom_field_tabs: tuple[str, ...] = (),
    custom_field_groups: tuple[str, ...] = (),
    custom_field_group_ids: tuple[int, ...] = (),
    custom_field_definition_ids: tuple[str | int, ...] = (),
    custom_field_names: tuple[str, ...] = (),
) -> list[dict[str, object]]:
    payload = tool_payload(
        await get_organization(
            ctx_never_elicit(),
            party_id="o42",
            client=client,
            get_organization_query=make_get_organization_query(client, custom_fields=catalog),
            custom_field_tabs=custom_field_tabs,
            custom_field_groups=custom_field_groups,
            custom_field_group_ids=custom_field_group_ids,
            custom_field_definition_ids=cast(Sequence[CoercedId], custom_field_definition_ids),
            custom_field_names=custom_field_names,
        )
    )
    return [object_dict(item) for item in object_list(payload["custom_field_values"])]


class TestGetOrganizationCustomFields:
    @pytest.mark.asyncio
    @respx.mock
    async def test_organization_and_party_bean_values_resolve_on_the_same_record(
        self, client: BackstopClient
    ) -> None:
        _definitions_route(_ORG_BEAN_FIELD, _PARTY_BEAN_FIELD)
        respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(200, json=_org_custom_field_document(_ORG_AND_PARTY_VALUES))
        )

        values = await _organization_custom_fields(client, _catalog(client))

        assert [item["definition_id"] for item in values] == ["101", "202"]
        assert [item["entity_type"] for item in values] == ["OrganizationBean", "PartyBean"]
        assert [item["value"] for item in values] == ["org-value", "party-value"]
        assert [item["tab_name"] for item in values] == ["Org Tab", "Party Tab"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_duplicate_names_stay_distinct_after_join(self, client: BackstopClient) -> None:
        _definitions_route(_SHARED_NAME_ORG, _SHARED_NAME_PARTY)
        respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(
                200,
                json=_org_custom_field_document(
                    [
                        {"definitionId": 301, "name": "Shared Name", "value": "first"},
                        {"definitionId": 302, "name": "Shared Name", "value": "second"},
                    ]
                ),
            )
        )

        values = await _organization_custom_fields(client, _catalog(client))

        assert [(item["name"], item["definition_id"]) for item in values] == [
            ("Shared Name", "301"),
            ("Shared Name", "302"),
        ]
        assert [item["layout_name"] for item in values] == ["First Layout", "Second Layout"]
        assert [item["group_name"] for item in values] == ["First Group", "Second Group"]
        assert [item["tab_name"] for item in values] == ["First Tab", "Second Tab"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_selects_by_tab_group_name_group_id_definition_id_and_name(
        self, client: BackstopClient
    ) -> None:
        _definitions_route(_ORG_BEAN_FIELD, _PARTY_BEAN_FIELD, _SHARED_NAME_ORG)
        respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(
                200,
                json=_org_custom_field_document(
                    [
                        *_ORG_AND_PARTY_VALUES,
                        {"definitionId": 301, "name": "Shared Name", "value": "first"},
                    ]
                ),
            )
        )
        catalog = _catalog(client)

        by_tab = await _organization_custom_fields(client, catalog, custom_field_tabs=("org tab",))
        by_tabs = await _organization_custom_fields(
            client, catalog, custom_field_tabs=("Org Tab", "Party Tab")
        )
        by_group = await _organization_custom_fields(
            client, catalog, custom_field_groups=("PARTY GROUP",)
        )
        by_group_id = await _organization_custom_fields(
            client, catalog, custom_field_group_ids=(31,)
        )
        by_definition_id = await _organization_custom_fields(
            client, catalog, custom_field_definition_ids=("101",)
        )
        by_numeric_definition_id = await _organization_custom_fields(
            client, catalog, custom_field_definition_ids=(101,)
        )
        by_name = await _organization_custom_fields(
            client, catalog, custom_field_names=("org field",)
        )
        combined = await _organization_custom_fields(
            client,
            catalog,
            custom_field_tabs=("Org Tab",),
            custom_field_names=("Org Field",),
            custom_field_group_ids=(11,),
        )
        combined_miss = await _organization_custom_fields(
            client,
            catalog,
            custom_field_tabs=("Org Tab",),
            custom_field_names=("Party Field",),
        )

        assert [item["definition_id"] for item in by_tab] == ["101"]
        assert [item["definition_id"] for item in by_tabs] == ["101", "202"]
        assert [item["definition_id"] for item in by_group] == ["202"]
        assert [item["definition_id"] for item in by_group_id] == ["301"]
        assert [item["definition_id"] for item in by_definition_id] == ["101"]
        assert [item["definition_id"] for item in by_numeric_definition_id] == ["101"]
        assert [item["definition_id"] for item in by_name] == ["101"]
        assert [item["definition_id"] for item in combined] == ["101"]
        assert combined_miss == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_value_outside_select_options_is_kept_and_flagged(
        self, client: BackstopClient
    ) -> None:
        _definitions_route(_PICK_FIELD, _LISTED_PICK_FIELD)
        respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(
                200,
                json=_org_custom_field_document(
                    [
                        {"definitionId": 401, "name": "Pick Field", "value": "Legacy Value"},
                        {
                            "definitionId": 402,
                            "name": "Listed Pick Field",
                            "value": "Listed Option",
                        },
                    ]
                ),
            )
        )

        values = await _organization_custom_fields(client, _catalog(client))

        assert values[0]["value"] == "Legacy Value"
        assert values[0]["outside_current_options"] is True
        assert values[1]["value"] == "Listed Option"
        assert "outside_current_options" not in values[1]

    @pytest.mark.asyncio
    @respx.mock
    async def test_entity_value_is_a_structured_reference(self, client: BackstopClient) -> None:
        _definitions_route(_ENTITY_PERSON_FIELD, _ENTITY_ACCOUNT_FIELD)
        person_link = f"{BASE_URL}/people/p99"
        respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(
                200,
                json=_org_custom_field_document(
                    [
                        {
                            "definitionId": 501,
                            "name": "Related Person",
                            "value": {
                                "resourceType": "people",
                                "resourceId": "p99",
                                "resourceLink": person_link,
                            },
                        },
                        {
                            "definitionId": 502,
                            "name": "Related Account",
                            "value": {
                                "resourceType": "accounts",
                                "resourceId": "a1",
                                "resourceLink": f"{BASE_URL}/accounts/a1",
                            },
                        },
                    ]
                ),
            )
        )

        values = await _organization_custom_fields(client, _catalog(client))

        person_ref = object_dict(values[0]["value"])
        account_ref = object_dict(values[1]["value"])
        assert person_ref == {
            "id": "p99",
            "resource_type": "people",
            "resource_link": person_link,
            "search_type": "people",
        }
        assert account_ref == {
            "id": "a1",
            "resource_type": "accounts",
            "resource_link": f"{BASE_URL}/accounts/a1",
        }
        assert "search_type" not in account_ref
        assert "resourceId" not in person_ref

    @pytest.mark.asyncio
    @respx.mock
    async def test_one_party_get_and_at_most_one_catalog_walk(self, client: BackstopClient) -> None:
        definitions = _definitions_route(_ORG_BEAN_FIELD, _PARTY_BEAN_FIELD)
        org_get = respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(200, json=_org_custom_field_document(_ORG_AND_PARTY_VALUES))
        )
        catalog = _catalog(client)

        await _organization_custom_fields(client, catalog)
        await _organization_custom_fields(client, catalog)

        paths = [request.url.path for request in recorded_requests(respx.calls)]
        assert org_get.call_count == 2
        assert definitions.call_count == 1
        assert paths.count("/organizations/o42") == 2
        assert paths.count("/custom-field-definitions") == 1
        assert all(path in {"/organizations/o42", "/custom-field-definitions"} for path in paths)

    @pytest.mark.asyncio
    @respx.mock
    async def test_catalog_fetch_failure_on_a_cold_cache_still_returns_the_record(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/custom-field-definitions").mock(
            return_value=httpx.Response(500, json={"error": "unavailable"})
        )
        respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(200, json=_org_custom_field_document(_ORG_AND_PARTY_VALUES))
        )

        payload = tool_payload(
            await get_organization(
                ctx_never_elicit(),
                party_id="o42",
                client=client,
                get_organization_query=make_get_organization_query(
                    client, custom_fields=_catalog(client)
                ),
            )
        )

        assert object_dict(payload["organization"])["name"] == "Koch Investments Group"
        assert object_list(payload["custom_field_values"]) == []
        assert "regularCustomFieldValues" not in object_dict(payload["organization"])

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_malformed_value_row_is_skipped_and_the_party_still_resolves(
        self, client: BackstopClient
    ) -> None:
        definitions = _definitions_route(_ORG_BEAN_FIELD)
        org_get = respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(
                200,
                json=_org_custom_field_document(
                    [
                        {"definitionId": 101, "name": "Org Field", "value": "org-value"},
                        {"definitionId": 101, "name": 123, "value": "malformed"},
                    ]
                ),
            )
        )

        result = tool_model(
            await get_organization(
                ctx_never_elicit(),
                party_id="o42",
                client=client,
                get_organization_query=make_get_organization_query(
                    client, custom_fields=_catalog(client)
                ),
            ),
            OrganizationResolvedResponse,
        )

        assert result.status == "resolved"
        assert [item.definition_id for item in result.custom_field_values] == ["101"]
        assert result.custom_field_values[0].value == "org-value"
        assert result.organization.name == "Koch Investments Group"

        paths = [request.url.path for request in recorded_requests(respx.calls)]
        assert org_get.call_count == 1
        assert definitions.call_count <= 1
        assert paths.count("/organizations/o42") == 1
        assert paths.count("/custom-field-definitions") <= 1
        assert all(path in {"/organizations/o42", "/custom-field-definitions"} for path in paths)
