"""`create_employment`: registered and wired through the command factory."""

from collections.abc import AsyncGenerator
from datetime import date

import httpx
import pytest
import respx
from pydantic import TypeAdapter

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.org_people_writes import (
    CreatedEmploymentResponse,
    CreateEmploymentCommand,
    CreateEmploymentInput,
    EntityRelationshipTypesService,
    get_create_employment_command_factory,
)
from backstop_mcp.features.org_people_writes.tools.create_employment import create_employment
from backstop_mcp.server.tools import TOOLS
from tests.features.party_resolver.helpers import ctx_never_elicit, make_resolve_party_query
from tests.helpers import (
    BASE_URL,
    build_employment_index_factory,
    client_factory,
    credential,
    resource,
)
from tests.server.tools.helpers import tool_model

_PERSON_ID = "p1"
_ORG_ID = "o1"
_REL_ID = "127921501"
_START = date(2026, 1, 15)
_CATALOG_ID = "ert-current-from-mock"
_EMPLOYMENT: TypeAdapter[CreateEmploymentInput] = TypeAdapter(CreateEmploymentInput)


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def make_command(client: BackstopClient) -> CreateEmploymentCommand:
    return get_create_employment_command_factory(
        client,
        entity_relationship_types_service=EntityRelationshipTypesService.with_ttl_minutes(
            client=client,
            ttl_minutes=60,
            rules=build_employment_index_factory().rules,
        ),
    )


def _types_catalog() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": [
                resource(_CATALOG_ID, "entity-relationship-types", name="is employee of"),
                resource("ert-former", "entity-relationship-types", name="is a former employee of"),
            ],
            "meta": {"totalResourceCount": 2},
            "links": {"next": None},
        },
    )


def _relationship_document(*, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        json={
            "data": {
                "id": _REL_ID,
                "type": "entity-relationships",
                "attributes": {"startDate": _START.isoformat()},
            }
        },
    )


class TestCreateEmployment:
    def test_is_registered(self) -> None:
        assert create_employment in TOOLS

    @respx.mock
    async def test_creates_employment_for_trusted_ids(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/entity-relationship-types").mock(return_value=_types_catalog())
        respx.post(f"{BASE_URL}/entity-relationships").mock(
            return_value=_relationship_document(status=201)
        )
        respx.get(f"{BASE_URL}/entity-relationships/{_REL_ID}").mock(
            return_value=_relationship_document()
        )

        result = tool_model(
            await create_employment(
                ctx_never_elicit(),
                employment=_EMPLOYMENT.validate_python(
                    {
                        "party_id": _PERSON_ID,
                        "search_type": "people",
                        "organization_id": _ORG_ID,
                        "start_date": _START.isoformat(),
                    }
                ),
                resolve_party_query=make_resolve_party_query(client),
                create_employment_command=make_command(client),
            ),
            CreatedEmploymentResponse,
        )

        assert result.id == _REL_ID
        assert result.start_date == _START
        assert result.created_mirror_row is True
        assert result.warnings == ()
