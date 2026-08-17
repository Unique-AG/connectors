from collections.abc import Callable

import httpx
import pytest
import respx

from backstop_mcp.features.data_hygiene import AsOf, DepartureSignal, EmploymentLinkResponse
from backstop_mcp.features.party_resolver import (
    PartyAmbiguousResponse,
    PartyCandidateResponse,
    ResolvedPartyResponse,
)
from backstop_mcp.server.tools.get_person import PersonResolvedResponse, get_person
from tests.features.data_hygiene.helpers import (
    EMPLOYEE_TYPE,
    FORMER_TYPE,
    person_org,
    relationship_types,
)
from tests.features.party_resolver.helpers import (
    BASE_URL,
    collection,
    ctx_decline,
    ctx_never_elicit,
    resource,
)
from tests.server.tools.helpers import object_dict, tool_model, tool_payload

type ConnectUser = Callable[..., object]

# The measured trio on one live person: two retired addresses from previous firms alongside the
# current one.
CONTACT_EMAILS: list[dict[str, object]] = [
    {
        "type": "contact-emails",
        "id": "e1",
        "attributes": {"sortOrder": 0, "retired": True, "email": "bbetten@macfound.org"},
    },
    {
        "type": "contact-emails",
        "id": "e2",
        "attributes": {"sortOrder": 0, "retired": True, "email": "kent.voss@kochind.com"},
    },
    {
        "type": "contact-emails",
        "id": "e3",
        "attributes": {"sortOrder": 0, "retired": False, "email": "vossk@kochinvests.com"},
    },
]


def _person_document(
    *type_ids: str,
    attributes: dict[str, object] | None = None,
    relationships: dict[str, object] | None = None,
    included: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """A person GET shaped like the real nested-include response.

    One relationship per type id, all pointing at the same organization, with each type's own
    resource side-loaded alongside them — which is where the type name comes from now.
    `relationships` / `included` add whatever a requested include would have side-loaded.
    """
    employment_links = [
        person_org(f"er{index}", type_id=type_id, source_id="p9")
        for index, type_id in enumerate(type_ids)
    ]
    types = relationship_types(*dict.fromkeys(type_ids))
    return {
        "data": {
            "type": "people",
            "id": "p9",
            "attributes": attributes
            or {
                "name": "Jane Doe",
                "modifiedTimestamp": "2023-01-01T00:00:00Z",
                "modifiedBy": "crm-admin",
            },
            "relationships": {
                "entityRelationships": {
                    "data": [
                        {"type": "entity-relationships", "id": item["id"]}
                        for item in employment_links
                    ]
                },
                **(relationships or {}),
            },
        },
        "included": [*employment_links, *types, *(included or [])],
    }


class TestGetPerson:
    @pytest.mark.asyncio
    @respx.mock
    async def test_unique_search_fetches_person_and_employment_links(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-person-1", "person-bob")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json=collection(resource("p9", "people", name="Jane Doe")),
            )
        )
        person_get = respx.get(f"{BASE_URL}/people/p9").mock(
            return_value=httpx.Response(200, json=_person_document(FORMER_TYPE))
        )
        types_get = respx.get(f"{BASE_URL}/entity-relationship-types").mock(
            return_value=httpx.Response(200, json={"data": [], "links": {}})
        )

        result = tool_model(
            await get_person(ctx_never_elicit(), search="Jane Doe"),
            PersonResolvedResponse,
        )

        assert result.resolved == ResolvedPartyResponse(
            id="p9", search_type="people", name="Jane Doe"
        )
        assert result.employments == [
            EmploymentLinkResponse(
                status="former",
                person_id="p9",
                person_type="people",
                organization_id="o1",
                organization_type="organizations",
                signal=DepartureSignal.FORMER_TYPE,
                end_date=None,
                relationship_type_id=FORMER_TYPE,
                relationship_type_name="is a former employee of",
            )
        ]
        assert result.as_of == AsOf(
            modified_timestamp="2023-01-01T00:00:00Z", modified_by="crm-admin"
        )
        # The nested hop is what populates each relationship's own type linkage, and it has to
        # arrive on this one GET: without it the detector has no type id to classify.
        sent = str(person_get.calls.last.request.url).replace("%3D", "=").replace("%2C", ",")
        assert "include=entityRelationships,entityRelationships.entityRelationshipType" in sent
        assert types_get.call_count == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_undated_tie_at_the_same_org_breaks_toward_departed(
        self, connect_user: ConnectUser
    ) -> None:
        """A person carrying both `is a former employee of` and `is employee of` against one
        organization, neither dated: `EmploymentIndex`'s winner-per-pair fold breaks an undated
        tie toward `FORMER` — under-reporting a departure is the costlier error."""
        await connect_user("user-person-3", "person-dave")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json=collection(resource("p9", "people", name="Jane Doe")),
            )
        )
        respx.get(f"{BASE_URL}/people/p9").mock(
            return_value=httpx.Response(200, json=_person_document(FORMER_TYPE, EMPLOYEE_TYPE))
        )

        result = tool_model(
            await get_person(ctx_never_elicit(), search="Jane Doe"),
            PersonResolvedResponse,
        )

        assert len(result.employments) == 1
        assert result.employments[0].status == "former"
        assert result.employments[0].organization_id == "o1"

    @pytest.mark.asyncio
    @respx.mock
    async def test_fetches_resolved_collection_when_hit_is_not_people(
        self, connect_user: ConnectUser
    ) -> None:
        """Name search uses shared PERSON_* types; a contact hit must GET /contacts/{id}."""
        await connect_user("user-person-4", "person-erin-contact")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json=collection(resource("c9", "contacts", name="Jane Contact")),
            )
        )
        contact_get = respx.get(f"{BASE_URL}/contacts/c9").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "type": "contacts",
                        "id": "c9",
                        "attributes": {"name": "Jane Contact"},
                        "relationships": {"entityRelationships": {"data": []}},
                    },
                    "included": [],
                },
            )
        )
        people_get = respx.get(url__regex=rf"{BASE_URL}/people/\w+").mock(
            return_value=httpx.Response(200, json={})
        )

        result = tool_model(
            await get_person(ctx_never_elicit(), search="Jane Contact"),
            PersonResolvedResponse,
        )

        assert result.resolved == ResolvedPartyResponse(
            id="c9", search_type="contacts", name="Jane Contact"
        )
        assert contact_get.call_count == 1
        assert people_get.call_count == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_trusted_contact_party_id_fetches_contacts_collection(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-person-5", "person-frank")  # pyright: ignore[reportGeneralTypeIssues]

        contact_get = respx.get(f"{BASE_URL}/contacts/c9").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "type": "contacts",
                        "id": "c9",
                        "attributes": {"name": "Jane Contact"},
                        "relationships": {"entityRelationships": {"data": []}},
                    },
                    "included": [],
                },
            )
        )
        people_get = respx.get(url__regex=rf"{BASE_URL}/people/\w+").mock(
            return_value=httpx.Response(200, json={})
        )

        result = tool_model(
            await get_person(
                ctx_never_elicit(),
                party_id="c9",
                search_type="contacts",
            ),
            PersonResolvedResponse,
        )

        assert result.resolved == ResolvedPartyResponse(
            id="c9", search_type="contacts", name="Jane Contact"
        )
        assert contact_get.call_count == 1
        assert people_get.call_count == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_ambiguous_search_skips_person_get(self, connect_user: ConnectUser) -> None:
        await connect_user("user-person-2", "person-carol")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json=collection(
                    resource("p1", "people", name="Jane A"),
                    resource("p2", "people", name="Jane B"),
                ),
            )
        )
        person_get = respx.get(url__regex=rf"{BASE_URL}/people/\w+").mock(
            return_value=httpx.Response(200, json={})
        )

        result = tool_model(
            await get_person(ctx_decline(), search="Jane"),
            PartyAmbiguousResponse,
        )

        assert result == PartyAmbiguousResponse(
            query="Jane",
            scope="people",
            candidates=[
                PartyCandidateResponse(
                    key="people:p1",
                    label="Jane A",
                    id="p1",
                    search_type="people",
                    name="Jane A",
                ),
                PartyCandidateResponse(
                    key="people:p2",
                    label="Jane B",
                    id="p2",
                    search_type="people",
                    name="Jane B",
                ),
            ],
        )
        assert person_get.call_count == 0

    def test_docstring_instructs_model_to_relay_employments(self) -> None:
        doc = get_person.__doc__ or ""
        assert "employments" in doc
        assert "relay" in doc.lower()

    @pytest.mark.asyncio
    @respx.mock
    async def test_does_not_declare_glossary_meta(self, connect_user: ConnectUser) -> None:
        await connect_user("user-person-glossary", "person-glossary")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json=collection(resource("p9", "people", name="Jane Doe")),
            )
        )
        respx.get(f"{BASE_URL}/people/p9").mock(
            return_value=httpx.Response(200, json=_person_document(FORMER_TYPE))
        )

        result = tool_model(
            await get_person(ctx_never_elicit(), search="Jane Doe"),
            PersonResolvedResponse,
        )

        assert "glossary_meta" not in PersonResolvedResponse.model_fields
        assert "glossary_meta" not in result.model_dump()
        assert "glossary_meta" not in (get_person.__doc__ or "")


class TestGetPersonIncludes:
    @pytest.mark.asyncio
    @respx.mock
    async def test_retired_addresses_arrive_flagged_beside_the_live_one(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-person-includes-1", "person-emails")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(f"{BASE_URL}/people/p9").mock(
            return_value=httpx.Response(
                200,
                json=_person_document(
                    FORMER_TYPE,
                    relationships={
                        "contactEmails": {
                            "data": [
                                {"type": "contact-emails", "id": email["id"]}
                                for email in CONTACT_EMAILS
                            ]
                        }
                    },
                    included=CONTACT_EMAILS,
                ),
            )
        )

        result = tool_model(
            await get_person(ctx_never_elicit(), party_id="p9", include=["email_addresses"]),
            PersonResolvedResponse,
        )

        included = result.included
        assert included is not None
        assert included.email_addresses is not None
        assert [(email.email, email.retired) for email in included.email_addresses] == [
            ("bbetten@macfound.org", True),
            ("kent.voss@kochind.com", True),
            ("vossk@kochinvests.com", False),
        ]

    @pytest.mark.asyncio
    @respx.mock
    async def test_requested_includes_ride_along_with_the_employment_side_load(
        self, connect_user: ConnectUser
    ) -> None:
        """One GET carries both, and the empty plan must not leave a comma behind."""
        await connect_user("user-person-includes-2", "person-composed-include")  # pyright: ignore[reportGeneralTypeIssues]

        person_get = respx.get(f"{BASE_URL}/people/p9").mock(
            return_value=httpx.Response(
                200,
                json=_person_document(
                    FORMER_TYPE,
                    relationships={
                        "contactEmails": {"data": [{"type": "contact-emails", "id": "e3"}]},
                        "company": {"data": {"type": "organizations", "id": "o1"}},
                    },
                    included=[
                        CONTACT_EMAILS[2],
                        {
                            "type": "organizations",
                            "id": "o1",
                            "attributes": {
                                "name": "Koch Investments Group",
                                "legalName": "Koch Investments Group, LLC",
                                "website": "www.kochinvests.com",
                                "city": "Scottsdale",
                                "state": "AZ",
                                "country": "United States of America",
                            },
                        },
                    ],
                ),
            )
        )

        result = tool_model(
            await get_person(
                ctx_never_elicit(), party_id="p9", include=["email_addresses", "company"]
            ),
            PersonResolvedResponse,
        )

        assert person_get.calls.last.request.url.params["include"] == (
            "entityRelationships,entityRelationships.entityRelationshipType,contactEmails,company"
        )
        included = result.included
        assert included is not None
        assert included.company is not None
        assert included.company.name == "Koch Investments Group"
        # The employment index reads the same document; asking for includes does not disturb it.
        assert [link.status for link in result.employments] == ["former"]
        assert result.employments[0].organization_id == "o1"

    @pytest.mark.asyncio
    @respx.mock
    async def test_omitting_include_leaves_no_included_key_and_no_trailing_comma(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-person-includes-3", "person-no-include")  # pyright: ignore[reportGeneralTypeIssues]

        person_get = respx.get(f"{BASE_URL}/people/p9").mock(
            return_value=httpx.Response(200, json=_person_document(EMPLOYEE_TYPE))
        )

        payload = tool_payload(await get_person(ctx_never_elicit(), party_id="p9"))

        assert "included" not in payload
        assert person_get.calls.last.request.url.params["include"] == (
            "entityRelationships,entityRelationships.entityRelationshipType"
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_the_person_tool_wires_locations_and_the_representative_too(
        self, connect_user: ConnectUser
    ) -> None:
        """The person table maps the same two relationship names the organization table does."""
        await connect_user("user-person-includes-4", "person-locations-rep")  # pyright: ignore[reportGeneralTypeIssues]

        person_get = respx.get(f"{BASE_URL}/people/p9").mock(
            return_value=httpx.Response(
                200,
                json=_person_document(
                    EMPLOYEE_TYPE,
                    relationships={
                        "contactLocations": {
                            "data": [{"type": "contact-locations", "id": "loc-1"}]
                        },
                        "representative": {"data": {"type": "system-users", "id": "u1"}},
                    },
                    included=[
                        {
                            "type": "contact-locations",
                            "id": "loc-1",
                            "attributes": {
                                "locationTitle": "Business",
                                "address": "18867 North Thompson Peak Parkway, Suite 250",
                                "city": "Scottsdale",
                                "state": "AZ",
                                "country": "United States of America",
                                "postalCode": "85255",
                                "phoneNumber": "(480) 419-3625",
                                "isPrimaryLocation": True,
                            },
                        },
                        {
                            "type": "system-users",
                            "id": "u1",
                            "attributes": {
                                "name": "Margaret Lucas",
                                "userName": "mlucas",
                                "email": "margaret.lucas@capstoneco.com",
                                "phoneNumber": "12122321462",
                            },
                        },
                    ],
                ),
            )
        )

        result = tool_model(
            await get_person(
                ctx_never_elicit(), party_id="p9", include=["locations", "representative"]
            ),
            PersonResolvedResponse,
        )

        assert person_get.calls.last.request.url.params["include"] == (
            "entityRelationships,entityRelationships.entityRelationshipType,"
            "contactLocations,representative"
        )
        included = result.included
        assert included is not None
        assert included.locations is not None
        assert [one.location_title for one in included.locations] == ["Business"]
        assert included.representative is not None
        assert included.representative.user_name == "mlucas"


class TestGetPersonOmitsNullsFromTheWire:
    """The payload carries no nulls at all: an absent key means "no value", not "we did not look".

    Asserted on the raw payload, because `tool_model` reads absent and null identically and would
    not notice this behaviour changing in either direction.
    """

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_null_backstop_attribute_is_not_a_key_but_a_filled_one_is(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-person-nulls-1", "person-null-attribute")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(f"{BASE_URL}/people/p9").mock(
            return_value=httpx.Response(
                200,
                json=_person_document(
                    EMPLOYEE_TYPE,
                    attributes={
                        "name": "Jane Doe",
                        "jobTitle": None,
                        "modifiedTimestamp": "2023-01-01T00:00:00Z",
                        "modifiedBy": "crm-admin",
                    },
                ),
            )
        )

        payload = tool_payload(await get_person(ctx_never_elicit(), party_id="p9"))

        person = object_dict(payload["person"])
        assert "jobTitle" not in person
        assert person["name"] == "Jane Doe"

    @pytest.mark.asyncio
    @respx.mock
    async def test_custom_field_values_survive_intact(self, connect_user: ConnectUser) -> None:
        """A plain dict, not a model, so nothing prunes it — write-back still round-trips."""
        await connect_user("user-person-nulls-2", "person-custom-fields")  # pyright: ignore[reportGeneralTypeIssues]

        custom_fields = [
            {"definitionId": 343439, "name": "Status", "value": "Attended - Web & Adio"}
        ]
        respx.get(f"{BASE_URL}/people/p9").mock(
            return_value=httpx.Response(
                200,
                json=_person_document(
                    EMPLOYEE_TYPE,
                    attributes={
                        "name": "Jane Doe",
                        "regularCustomFieldValues": custom_fields,
                        "modifiedTimestamp": "2023-01-01T00:00:00Z",
                        "modifiedBy": "crm-admin",
                    },
                ),
            )
        )

        payload = tool_payload(await get_person(ctx_never_elicit(), party_id="p9"))

        assert object_dict(payload["person"])["regularCustomFieldValues"] == custom_fields

    @pytest.mark.asyncio
    @respx.mock
    async def test_as_of_is_absent_when_backstop_records_no_provenance(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-person-nulls-3", "person-no-provenance")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(f"{BASE_URL}/people/p9").mock(
            return_value=httpx.Response(
                200, json=_person_document(EMPLOYEE_TYPE, attributes={"name": "Jane Doe"})
            )
        )

        payload = tool_payload(await get_person(ctx_never_elicit(), party_id="p9"))

        assert "as_of" not in payload
