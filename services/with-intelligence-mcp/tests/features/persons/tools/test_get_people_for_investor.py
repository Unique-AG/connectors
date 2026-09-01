"""`get_people_for_investor`: role selection, departures, and the disagreeing counts."""

import httpx
import respx

from tests.helpers import BASE_URL, build_client, page_body, sent_query
from with_intelligence_mcp.features.investors import InvestorAmbiguousResponse
from with_intelligence_mcp.features.persons import PeopleForInvestorResponse
from with_intelligence_mcp.features.persons.tools.get_people_for_investor import (
    get_people_for_investor,
)

INVESTOR = {"id": 2504, "name": "Example Retirement System (ERS)", "contacts_total": 64}


def _person(person_id: int, name: str, roles: list[dict[str, object]]) -> dict[str, object]:
    return {"id": person_id, "full_name": name, "person_roles": roles}


def _role(org_id: int, **extra: object) -> dict[str, object]:
    return {"organisation": {"id": org_id, "name": f"Org {org_id}"}, **extra}


def _mock_roster(people: list[dict[str, object]], *, total: int) -> None:
    listing = [{"id": p["id"], "name": p["full_name"]} for p in people]
    respx.get(f"{BASE_URL}/v3/persons").mock(
        return_value=httpx.Response(200, json=page_body(listing, total=total))
    )
    for person in people:
        respx.get(f"{BASE_URL}/v3/persons/{person['id']}").mock(
            return_value=httpx.Response(200, json=person)
        )
    respx.get(f"{BASE_URL}/v3/investors/2504").mock(return_value=httpx.Response(200, json=INVESTOR))


class TestRoleSelection:
    @respx.mock
    async def test_uses_the_role_at_the_investor_asked_about(self) -> None:
        """A person's roles span every employer; the first one would credit the wrong firm."""
        _mock_roster(
            [
                _person(
                    1,
                    "A. Allocator",
                    [
                        _role(999, job_title="Analyst at a previous employer"),
                        _role(2504, job_title="Director of Hedge Funds"),
                    ],
                )
            ],
            total=1,
        )
        client, _ = build_client()
        result = await get_people_for_investor(investor_id=2504, client=client)
        assert isinstance(result, PeopleForInvestorResponse)
        assert result.people[0].job_title == "Director of Hedge Funds"

    @respx.mock
    async def test_matches_on_org_entity_id_too(self) -> None:
        _mock_roster(
            [
                _person(
                    1,
                    "B. Allocator",
                    [{"organisation": {"org_entity_id": 2504}, "job_title": "CIO"}],
                )
            ],
            total=1,
        )
        client, _ = build_client()
        result = await get_people_for_investor(investor_id=2504, client=client)
        assert isinstance(result, PeopleForInvestorResponse)
        assert result.people[0].job_title == "CIO"

    @respx.mock
    async def test_prefers_a_current_role_over_one_they_left(self) -> None:
        _mock_roster(
            [
                _person(
                    1,
                    "C. Allocator",
                    [
                        _role(2504, job_title="Former Analyst", end_date="2021-01-01"),
                        _role(2504, job_title="Head of Manager Selection"),
                    ],
                )
            ],
            total=1,
        )
        client, _ = build_client()
        result = await get_people_for_investor(investor_id=2504, client=client)
        assert isinstance(result, PeopleForInvestorResponse)
        assert result.people[0].job_title == "Head of Manager Selection"
        assert result.people[0].is_current is True

    @respx.mock
    async def test_a_person_with_no_role_here_still_returns_their_name(self) -> None:
        _mock_roster([_person(1, "D. Allocator", [_role(999, job_title="Elsewhere")])], total=1)
        client, _ = build_client()
        result = await get_people_for_investor(investor_id=2504, client=client)
        assert isinstance(result, PeopleForInvestorResponse)
        assert result.people[0].name == "D. Allocator"
        assert result.people[0].job_title is None


class TestDepartures:
    @respx.mock
    async def test_an_ended_role_is_flagged_not_hidden(self) -> None:
        """Writing to someone who has left is the mistake this flag exists to prevent."""
        _mock_roster(
            [
                _person(
                    1,
                    "E. Allocator",
                    [_role(2504, job_title="Former CIO", end_date="2024-06-30")],
                )
            ],
            total=1,
        )
        client, _ = build_client()
        result = await get_people_for_investor(investor_id=2504, client=client)
        assert isinstance(result, PeopleForInvestorResponse)
        assert result.people[0].is_current is False
        assert result.people[0].role_ended == "2024-06-30"


class TestContactDetails:
    @respx.mock
    async def test_surfaces_title_seniority_email_and_main_contact_flag(self) -> None:
        _mock_roster(
            [
                _person(
                    1,
                    "F. Allocator",
                    [
                        _role(
                            2504,
                            job_title="Director of Hedge Funds",
                            seniority={"id": 3, "name": "Director"},
                            specialisms={"id": 1, "name": "Hedge Funds"},
                            primary_email="f.allocator@example.invalid",
                            office_phone="+1 555 0100",
                            main_for_organisation=True,
                        )
                    ],
                )
            ],
            total=1,
        )
        client, _ = build_client()
        result = await get_people_for_investor(investor_id=2504, client=client)
        assert isinstance(result, PeopleForInvestorResponse)
        person = result.people[0]
        assert person.seniority == "Director"
        assert person.specialism == "Hedge Funds"
        assert person.email == "f.allocator@example.invalid"
        assert person.phone == "+1 555 0100"
        assert person.is_main_contact is True


class TestCountsAndScoping:
    @respx.mock
    async def test_reports_the_person_search_total(self) -> None:
        """It disagrees with the investor record's contact count; both are reported, neither
        is presented as the truth."""
        _mock_roster([_person(1, "G. Allocator", [_role(2504)])], total=12)
        client, _ = build_client()
        result = await get_people_for_investor(investor_id=2504, client=client)
        assert isinstance(result, PeopleForInvestorResponse)
        assert result.total_at_organisation == 12
        assert result.returned == 1

    @respx.mock
    async def test_scopes_the_search_by_organisation_and_package(self) -> None:
        route = respx.get(f"{BASE_URL}/v3/persons").mock(
            return_value=httpx.Response(200, json=page_body([], total=0))
        )
        respx.get(f"{BASE_URL}/v3/investors/2504").mock(
            return_value=httpx.Response(200, json=INVESTOR)
        )
        client, _ = build_client()
        _ = await get_people_for_investor(investor_id=2504, client=client)
        query = sent_query(route)
        assert "organisation_id=2504" in query
        assert "asset_class_group=hfm" in query

    @respx.mock
    async def test_an_ambiguous_name_asks_before_fetching_anyone(self) -> None:
        respx.get(f"{BASE_URL}/v3/investors").mock(
            return_value=httpx.Response(
                200,
                json=page_body(
                    [{"id": 1, "name": "Virginia A"}, {"id": 2, "name": "Virginia B"}], total=20
                ),
            )
        )
        persons = respx.get(f"{BASE_URL}/v3/persons").mock(
            return_value=httpx.Response(200, json=page_body([], total=0))
        )
        client, _ = build_client()
        result = await get_people_for_investor(name="Virginia", client=client)
        assert isinstance(result, InvestorAmbiguousResponse)
        assert result.total_matches == 20
        assert persons.call_count == 0
