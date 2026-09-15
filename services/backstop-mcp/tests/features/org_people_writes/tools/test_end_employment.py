"""`end_employment`: registered and wired through the command factory."""

from collections.abc import AsyncGenerator
from datetime import date, timedelta

import httpx
import pytest
import respx
from pydantic import TypeAdapter

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.org_people_writes import (
    EndedEmploymentResponse,
    EndEmploymentCommand,
    EndEmploymentInput,
    get_end_employment_command_factory,
)
from backstop_mcp.features.org_people_writes.tools.end_employment import end_employment
from backstop_mcp.server.tools import TOOLS
from tests.features.data_hygiene.helpers import EMPLOYEE_TYPE, person_org, relationship_types
from tests.features.party_resolver.helpers import ctx_never_elicit, make_resolve_party_query
from tests.helpers import BASE_URL, build_employment_index_factory, client_factory, credential
from tests.server.tools.helpers import tool_model

_PERSON_ID = "p1"
_ORG_ID = "o1"
_REL_ID = "127921399"
_PAST = date.today() - timedelta(days=1)
_EMPLOYMENT: TypeAdapter[EndEmploymentInput] = TypeAdapter(EndEmploymentInput)


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


class TestEndEmployment:
    def test_is_registered(self) -> None:
        assert end_employment in TOOLS

    @respx.mock
    async def test_ends_employment_for_trusted_ids(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/people/{_PERSON_ID}/entityRelationships").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [person_org(_REL_ID, source_id=_PERSON_ID, dest_id=_ORG_ID)],
                    "included": relationship_types(EMPLOYEE_TYPE),
                    "links": {"next": None},
                },
            )
        )
        respx.patch(f"{BASE_URL}/entity-relationships/{_REL_ID}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "id": _REL_ID,
                        "type": "entity-relationships",
                        "attributes": {"endDate": _PAST.isoformat()},
                    }
                },
            )
        )
        respx.get(f"{BASE_URL}/entity-relationships/{_REL_ID}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "id": _REL_ID,
                        "type": "entity-relationships",
                        "attributes": {"endDate": _PAST.isoformat()},
                    }
                },
            )
        )

        result = tool_model(
            await end_employment(
                ctx_never_elicit(),
                employment=_EMPLOYMENT.validate_python(
                    {
                        "party_id": _PERSON_ID,
                        "search_type": "people",
                        "organization_id": _ORG_ID,
                        "end_date": _PAST.isoformat(),
                    }
                ),
                resolve_party_query=make_resolve_party_query(client),
                end_employment_command=make_command(client),
            ),
            EndedEmploymentResponse,
        )

        assert result.id == _REL_ID
        assert result.end_date == _PAST
        assert result.warnings == ()
