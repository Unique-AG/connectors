from collections.abc import Callable

import httpx
import pytest
import respx

from backstop_mcp.features.data_hygiene import AsOf
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
from tests.server.tools.helpers import tool_model

type ConnectUser = Callable[..., object]


def _person_document(*type_ids: str) -> dict[str, object]:
    """A person GET shaped like the real nested-include response.

    One relationship per type id, all pointing at the same organization, with each type's own
    resource side-loaded alongside them — which is where the type name comes from now.
    """
    relationships = [
        person_org(f"er{index}", type_id=type_id, source_id="p9")
        for index, type_id in enumerate(type_ids)
    ]
    types = relationship_types(*dict.fromkeys(type_ids))
    return {
        "data": {
            "type": "people",
            "id": "p9",
            "attributes": {
                "name": "Jane Doe",
                "modifiedTimestamp": "2023-01-01T00:00:00Z",
                "modifiedBy": "crm-admin",
            },
            "relationships": {
                "entityRelationships": {
                    "data": [
                        {"type": "entity-relationships", "id": item["id"]} for item in relationships
                    ]
                }
            },
        },
        "included": [*relationships, *types],
    }


class TestGetPerson:
    @pytest.mark.asyncio
    @respx.mock
    async def test_unique_search_fetches_person_and_flags_departed(
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
        assert result.departed is True
        assert len(result.departures) == 1
        departure = result.departures[0]
        assert departure.signal == "former_relationship_type"
        assert departure.relationship_type_name == "is a former employee of"
        assert departure.organization_id == "o1"
        # The type carried the signal; this tenant recorded no date.
        assert departure.end_date is None
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

        assert result.departed is True
        assert len(result.departures) == 1
        assert result.departures[0].organization_id == "o1"

    @pytest.mark.asyncio
    @respx.mock
    async def test_fetches_resolved_collection_when_hit_is_not_people(
        self, connect_user: ConnectUser
    ) -> None:
        """Name search uses shared PERSON_* types; a contact hit must GET /contacts/{id}."""
        await connect_user("user-person-4", "person-erin")  # pyright: ignore[reportGeneralTypeIssues]

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
                    key="p1",
                    label="Jane A",
                    id="p1",
                    search_type="people",
                    name="Jane A",
                ),
                PartyCandidateResponse(
                    key="p2",
                    label="Jane B",
                    id="p2",
                    search_type="people",
                    name="Jane B",
                ),
            ],
        )
        assert person_get.call_count == 0

    def test_docstring_instructs_model_to_relay_departed_flag(self) -> None:
        doc = get_person.__doc__ or ""
        assert "departed" in doc
        assert "relay" in doc.lower()
