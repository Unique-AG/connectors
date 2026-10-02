"""`GetMeetingAttendeesQuery` maps the `/meeting-or-calls/{id}/attendees` page."""

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.activity_history import GetMeetingAttendeesQuery
from tests.helpers import BASE_URL


@pytest.mark.asyncio
@respx.mock
async def test_maps_id_company_and_job_title(client: BackstopClient) -> None:
    respx.get(f"{BASE_URL}/meeting-or-calls/75339077/attendees").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "341763893",
                        "type": "people",
                        "attributes": {
                            "name": "Doe, Jane",
                            "firstName": "Jane",
                            "lastName": "Doe",
                            "companyName": "Northwind Investment Advisors",
                            "jobTitle": "",
                            "isEmployee": True,
                        },
                    },
                    {
                        "id": "674101829",
                        "type": "people",
                        "attributes": {
                            "name": "Roe, Sam",
                            "companyName": "Northwind Investment Advisors",
                            "jobTitle": "Managing Director, Portfolio Manager",
                            "isEmployee": False,
                        },
                    },
                ]
            },
        )
    )

    attendees = await GetMeetingAttendeesQuery(client=client).run(resource_id="75339077")

    assert [(item.id, item.name, item.company_name, item.job_title) for item in attendees] == [
        ("341763893", "Doe, Jane", "Northwind Investment Advisors", None),
        (
            "674101829",
            "Roe, Sam",
            "Northwind Investment Advisors",
            "Managing Director, Portfolio Manager",
        ),
    ]
    assert not hasattr(attendees[1], "is_employee")
