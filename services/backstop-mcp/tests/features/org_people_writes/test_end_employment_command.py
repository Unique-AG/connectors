"""`EndEmploymentCommand`: one PATCH, `endDate` only, no type rewrite."""

from collections.abc import AsyncGenerator
from datetime import date, timedelta

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.custom_fields import CustomFieldFilters
from backstop_mcp.features.data_hygiene import DepartureSignal, EmploymentLinkResponse
from backstop_mcp.features.org_people import GetPersonQuery
from backstop_mcp.features.org_people_writes import (
    EndedEmploymentResponse,
    EndEmploymentCommand,
    get_end_employment_command_factory,
)
from tests.features.data_hygiene.helpers import (
    EMPLOYEE_TYPE,
    PORTAL_TYPE,
    person_org,
    relationship_types,
)
from tests.helpers import (
    BASE_URL,
    build_employment_index_factory,
    client_factory,
    credential,
    custom_fields_service,
    recorded_json_bodies,
)
from tests.server.tools.helpers import object_dict

_PERSON_ID = "p1"
_ORG_ID = "o1"
_REL_ID = "127921399"
_OTHER_REL_ID = "127921400"
_PAST = date.today() - timedelta(days=1)


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def make_command(client: BackstopClient) -> EndEmploymentCommand:
    return get_end_employment_command_factory(
        client,
        employment_index_factory=build_employment_index_factory(),
    )


def _collection(
    *resources: dict[str, object], type_ids: tuple[str, ...] = (EMPLOYEE_TYPE,)
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": list(resources),
            "included": relationship_types(*type_ids),
            "links": {"next": None},
        },
    )


def _relationship_document(*, end_date: str | None) -> httpx.Response:
    attributes: dict[str, object] = {}
    if end_date is not None:
        attributes["endDate"] = end_date
    return httpx.Response(
        200,
        json={
            "data": {
                "id": _REL_ID,
                "type": "entity-relationships",
                "attributes": attributes,
            }
        },
    )


def _open_employment(
    *, relationship_id: str = _REL_ID, dest_id: str = _ORG_ID
) -> dict[str, object]:
    return person_org(relationship_id, source_id=_PERSON_ID, dest_id=dest_id)


async def _run(client: BackstopClient, *, end_date: date = _PAST) -> EndedEmploymentResponse:
    result = await make_command(client).run(
        person_id=_PERSON_ID,
        person_search_type="people",
        organization_id=_ORG_ID,
        end_date=end_date,
    )
    assert isinstance(result, EndedEmploymentResponse)
    return result


class TestEndEmploymentCommand:
    @respx.mock
    async def test_one_patch_end_dates_the_relationship(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/people/{_PERSON_ID}/entityRelationships").mock(
            return_value=_collection(_open_employment())
        )
        route = respx.patch(f"{BASE_URL}/entity-relationships/{_REL_ID}").mock(
            return_value=_relationship_document(end_date=_PAST.isoformat())
        )
        respx.get(f"{BASE_URL}/entity-relationships/{_REL_ID}").mock(
            return_value=_relationship_document(end_date=_PAST.isoformat())
        )

        result = await _run(client)

        assert result.id == _REL_ID
        assert result.resource_type == "entity-relationships"
        assert result.end_date == _PAST
        assert result.warnings == ()
        assert route.call_count == 1

    @respx.mock
    async def test_payload_contains_only_end_date(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/people/{_PERSON_ID}/entityRelationships").mock(
            return_value=_collection(_open_employment())
        )
        route = respx.patch(f"{BASE_URL}/entity-relationships/{_REL_ID}").mock(
            return_value=_relationship_document(end_date=_PAST.isoformat())
        )
        respx.get(f"{BASE_URL}/entity-relationships/{_REL_ID}").mock(
            return_value=_relationship_document(end_date=_PAST.isoformat())
        )

        await _run(client)

        body = recorded_json_bodies(route)[0]
        data = object_dict(body["data"])
        assert data["type"] == "entity-relationships"
        assert data["id"] == _REL_ID
        assert object_dict(data["attributes"]) == {"endDate": _PAST.isoformat()}
        assert "relationships" not in data

    @respx.mock
    async def test_relationship_type_is_never_sent(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/people/{_PERSON_ID}/entityRelationships").mock(
            return_value=_collection(_open_employment())
        )
        route = respx.patch(f"{BASE_URL}/entity-relationships/{_REL_ID}").mock(
            return_value=_relationship_document(end_date=_PAST.isoformat())
        )
        respx.get(f"{BASE_URL}/entity-relationships/{_REL_ID}").mock(
            return_value=_relationship_document(end_date=_PAST.isoformat())
        )

        await _run(client)

        payload = recorded_json_bodies(route)[0]
        assert "entityRelationshipType" not in str(payload)

    @respx.mock
    async def test_missing_employment_pair_is_reported(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/people/{_PERSON_ID}/entityRelationships").mock(
            return_value=_collection(
                person_org(
                    "portal-1",
                    source_id=_PERSON_ID,
                    dest_id=_ORG_ID,
                    type_id=PORTAL_TYPE,
                ),
                type_ids=(PORTAL_TYPE,),
            )
        )
        route = respx.patch(url__regex=r".*").mock(
            return_value=_relationship_document(end_date=_PAST.isoformat())
        )

        with pytest.raises(ToolError, match=f"person {_PERSON_ID}.*organization {_ORG_ID}"):
            await _run(client)

        assert route.call_count == 0

    @respx.mock
    async def test_ambiguous_employment_pair_is_reported_rather_than_guessed(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/people/{_PERSON_ID}/entityRelationships").mock(
            return_value=_collection(
                _open_employment(relationship_id=_REL_ID),
                _open_employment(relationship_id=_OTHER_REL_ID),
            )
        )
        route = respx.patch(url__regex=r".*").mock(
            return_value=_relationship_document(end_date=_PAST.isoformat())
        )

        with pytest.raises(ToolError, match=f"{_REL_ID}.*{_OTHER_REL_ID}"):
            await _run(client)

        assert route.call_count == 0

    @respx.mock
    async def test_end_date_of_today_warns_that_it_is_not_yet_former(
        self, client: BackstopClient
    ) -> None:
        today = date.today()
        respx.get(f"{BASE_URL}/people/{_PERSON_ID}/entityRelationships").mock(
            return_value=_collection(_open_employment())
        )
        respx.patch(f"{BASE_URL}/entity-relationships/{_REL_ID}").mock(
            return_value=_relationship_document(end_date=today.isoformat())
        )
        respx.get(f"{BASE_URL}/entity-relationships/{_REL_ID}").mock(
            return_value=_relationship_document(end_date=today.isoformat())
        )

        result = await _run(client, end_date=today)

        assert result.end_date == today
        assert result.warnings
        assert "current contact" in result.warnings[0]

    @respx.mock
    async def test_after_end_employment_the_read_path_reports_the_link_as_former(
        self, client: BackstopClient
    ) -> None:
        ended = person_org(
            _REL_ID,
            source_id=_PERSON_ID,
            dest_id=_ORG_ID,
            end_date=_PAST.isoformat(),
        )
        respx.get(f"{BASE_URL}/people/{_PERSON_ID}/entityRelationships").mock(
            return_value=_collection(_open_employment())
        )
        respx.patch(f"{BASE_URL}/entity-relationships/{_REL_ID}").mock(
            return_value=_relationship_document(end_date=_PAST.isoformat())
        )
        respx.get(f"{BASE_URL}/entity-relationships/{_REL_ID}").mock(
            return_value=_relationship_document(end_date=_PAST.isoformat())
        )
        respx.get(f"{BASE_URL}/custom-field-definitions").mock(
            return_value=httpx.Response(200, json={"data": [], "links": {"next": None}})
        )
        respx.get(f"{BASE_URL}/people/{_PERSON_ID}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "type": "people",
                        "id": _PERSON_ID,
                        "attributes": {"name": "Jane Doe"},
                        "relationships": {
                            "entityRelationships": {
                                "data": [{"type": "entity-relationships", "id": _REL_ID}]
                            }
                        },
                    },
                    "included": [ended, *relationship_types(EMPLOYEE_TYPE)],
                },
            )
        )

        await _run(client)
        person = await GetPersonQuery(
            client=client,
            employment_index_factory=build_employment_index_factory(today=date.today()),
            custom_fields_service=custom_fields_service(client),
        ).run(
            search_type="people",
            party_id=_PERSON_ID,
            custom_fields_filters=CustomFieldFilters(),
        )

        assert person.employments == [
            EmploymentLinkResponse(
                status="former",
                person_id=_PERSON_ID,
                person_type="people",
                organization_id=_ORG_ID,
                organization_type="organizations",
                signal=DepartureSignal.END_DATE,
                end_date=_PAST,
                relationship_type_id=EMPLOYEE_TYPE,
                relationship_type_name="is employee of",
            )
        ]
