import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopAuthError, BackstopClient
from backstop_mcp.features.org_people.fetch import MAX_ORG_PEOPLE, fetch_people_for_organization
from tests.features.data_hygiene.helpers import (
    EMPLOYEE_TYPE,
    FORMER_MIRROR_TYPE,
    OWNS_ACCOUNT_TYPE,
    person_org,
    relationship_types,
)
from tests.helpers import BASE_URL, build_employment_index_factory, recorded_requests

_ORG = "o1"
_ER_URL = f"{BASE_URL}/organizations/{_ORG}/entityRelationships"
_EMPLOYEES_URL = f"{BASE_URL}/organizations/{_ORG}/employees"


def _er_page(*rows: dict[str, object], included: list[dict[str, object]]) -> httpx.Response:
    return httpx.Response(200, json={"data": list(rows), "included": included})


def _employees_page(
    *people: tuple[str, dict[str, object]],
    included: list[dict[str, object]] | None = None,
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": [
                {"id": person_id, "type": "employees", "attributes": attributes}
                for person_id, attributes in people
            ],
            "included": [] if included is None else included,
        },
    )


def _person_link(er_id: str, *, person_id: str, type_id: str) -> dict[str, object]:
    return person_org(
        er_id,
        source_type="people",
        source_id=person_id,
        dest_type="organizations",
        dest_id=_ORG,
        type_id=type_id,
    )


def _org_link(er_id: str, *, person_id: str, type_id: str) -> dict[str, object]:
    return person_org(
        er_id,
        source_type="organizations",
        source_id=_ORG,
        dest_type="people",
        dest_id=person_id,
        type_id=type_id,
    )


class TestFetchPeopleForOrganization:
    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_current_people_from_employee_includes(
        self, client: BackstopClient
    ) -> None:
        route = respx.get(_EMPLOYEES_URL).mock(
            return_value=_employees_page(
                (
                    "p1",
                    {
                        "name": "Glenn, Phil",
                        "jobTitle": "Tax Director",
                        "email": "phil@example.com",
                    },
                ),
                included=[
                    _person_link("er-current", person_id="p1", type_id=EMPLOYEE_TYPE),
                    _person_link("er-account", person_id="p3", type_id=OWNS_ACCOUNT_TYPE),
                    *relationship_types(EMPLOYEE_TYPE, OWNS_ACCOUNT_TYPE),
                ],
            )
        )

        respx.get(_ER_URL).mock(return_value=_er_page(included=[]))

        listing = await fetch_people_for_organization(
            client,
            build_employment_index_factory(),
            organization_id=_ORG,
            include_former=False,
        )

        assert [row.employment.person_id for row in listing.people] == ["p1"]
        assert listing.people[0].employment.status == "current"
        assert listing.people[0].card is not None
        assert listing.people[0].card.name == "Glenn, Phil"
        assert listing.people[0].card.job_title == "Tax Director"
        assert listing.former_omitted == 0
        assert listing.people_omitted == 0
        query = dict(route.calls.last.request.url.params)
        assert query["include"] == "entityRelationships,entityRelationships.entityRelationshipType"
        assert query["fields[employees]"] == "name,jobTitle,email,phone,companyName"
        assert any(
            request.url.path.endswith("/entityRelationships")
            for request in recorded_requests(respx.calls)
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_include_former_adds_org_entity_relationships(
        self, client: BackstopClient
    ) -> None:
        respx.get(_EMPLOYEES_URL).mock(
            return_value=_employees_page(
                ("p1", {"name": "Current"}),
                included=[
                    _person_link("er-current", person_id="p1", type_id=EMPLOYEE_TYPE),
                    *relationship_types(EMPLOYEE_TYPE),
                ],
            )
        )
        respx.get(_ER_URL).mock(
            return_value=_er_page(
                _org_link("er-former", person_id="p2", type_id=FORMER_MIRROR_TYPE),
                included=relationship_types(FORMER_MIRROR_TYPE),
            )
        )

        listing = await fetch_people_for_organization(
            client,
            build_employment_index_factory(),
            organization_id=_ORG,
            include_former=True,
        )

        by_id = {row.employment.person_id: row for row in listing.people}
        assert set(by_id) == {"p1", "p2"}
        assert by_id["p1"].employment.status == "current"
        assert by_id["p1"].card is not None
        assert by_id["p1"].card.name == "Current"
        assert by_id["p2"].employment.status == "former"
        assert by_id["p2"].card is None
        assert listing.former_omitted == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_former_only_org_reports_former_omitted(self, client: BackstopClient) -> None:
        respx.get(_EMPLOYEES_URL).mock(return_value=_employees_page())
        respx.get(_ER_URL).mock(
            return_value=_er_page(
                _org_link("er-former", person_id="p2", type_id=FORMER_MIRROR_TYPE),
                included=relationship_types(FORMER_MIRROR_TYPE),
            )
        )

        listing = await fetch_people_for_organization(
            client,
            build_employment_index_factory(),
            organization_id=_ORG,
            include_former=False,
        )

        assert listing.people == ()
        assert listing.former_omitted == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_current_plus_former_counts_omitted_former(self, client: BackstopClient) -> None:
        respx.get(_EMPLOYEES_URL).mock(
            return_value=_employees_page(
                ("p1", {"name": "Current"}),
                included=[
                    _person_link("er-current", person_id="p1", type_id=EMPLOYEE_TYPE),
                    *relationship_types(EMPLOYEE_TYPE),
                ],
            )
        )
        respx.get(_ER_URL).mock(
            return_value=_er_page(
                _org_link("er-former", person_id="p2", type_id=FORMER_MIRROR_TYPE),
                included=relationship_types(FORMER_MIRROR_TYPE),
            )
        )

        listing = await fetch_people_for_organization(
            client,
            build_employment_index_factory(),
            organization_id=_ORG,
            include_former=False,
        )

        assert [row.employment.person_id for row in listing.people] == ["p1"]
        assert listing.former_omitted == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_auth_failure_on_employees_aborts(self, client: BackstopClient) -> None:
        respx.get(_EMPLOYEES_URL).mock(return_value=httpx.Response(401))

        with pytest.raises(BackstopAuthError):
            await fetch_people_for_organization(
                client,
                build_employment_index_factory(),
                organization_id=_ORG,
                include_former=False,
            )

    @pytest.mark.asyncio
    @respx.mock
    async def test_caps_the_fan_out(
        self, client: BackstopClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("backstop_mcp.features.org_people.fetch.MAX_ORG_PEOPLE", 1)
        respx.get(_EMPLOYEES_URL).mock(
            return_value=_employees_page(
                ("p1", {"name": "A"}),
                ("p2", {"name": "B"}),
                included=[
                    _person_link("er-a", person_id="p1", type_id=EMPLOYEE_TYPE),
                    _person_link("er-b", person_id="p2", type_id=EMPLOYEE_TYPE),
                    *relationship_types(EMPLOYEE_TYPE),
                ],
            )
        )
        respx.get(_ER_URL).mock(return_value=_er_page(included=[]))

        listing = await fetch_people_for_organization(
            client,
            build_employment_index_factory(),
            organization_id=_ORG,
            include_former=False,
        )

        assert len(listing.people) == 1
        assert listing.people_omitted == 1
        assert MAX_ORG_PEOPLE == 500
