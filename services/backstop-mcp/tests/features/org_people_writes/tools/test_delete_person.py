"""`delete_person`: format a confirmation prompt, then delete unless elicitation was declined."""

from collections.abc import AsyncGenerator

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from fastmcp.server.elicitation import AcceptedElicitation
from pydantic import TypeAdapter

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.elicitation_utils import DELETE, DeletionChoice
from backstop_mcp.features.org_people_writes import (
    DeletedPersonResponse,
    DeletePartyWithLocationsCommand,
    DeletePersonInput,
    get_delete_party_with_locations_command_factory,
    get_modify_contact_location_command_factory,
)
from backstop_mcp.features.org_people_writes.tools.delete_person import delete_person
from backstop_mcp.server.tools import TOOLS
from tests.features.party_resolver.helpers import (
    FakeContext,
    as_context,
    ctx_accept,
    ctx_decline,
    ctx_no_elicitation_capability,
    make_resolve_party_query,
)
from tests.helpers import BASE_URL, client_factory, credential
from tests.server.tools.helpers import tool_model

_PERSON: TypeAdapter[DeletePersonInput] = TypeAdapter(DeletePersonInput)
_ID = "27871657"
_NAME = "Jane Doe"
_LOC_1 = "loc-1"
_LOC_2 = "loc-2"


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def make_command(client: BackstopClient) -> DeletePartyWithLocationsCommand:
    return get_delete_party_with_locations_command_factory(
        client,
        modify_contact_location_command=get_modify_contact_location_command_factory(client),
    )


def _person_document(*, location_ids: tuple[str, ...] = (_LOC_1, _LOC_2)) -> dict[str, object]:
    return {
        "data": {
            "id": _ID,
            "type": "people",
            "attributes": {"name": _NAME},
            "relationships": {
                "contactLocations": {
                    "data": [{"type": "contact-locations", "id": loc_id} for loc_id in location_ids]
                }
            },
        },
        "included": [
            {
                "type": "contact-locations",
                "id": loc_id,
                "attributes": {"locationTitle": f"Office {loc_id}"},
            }
            for loc_id in location_ids
        ],
    }


def _mock_cascade() -> tuple[respx.Route, respx.Route, respx.Route, respx.Route]:
    preview = respx.get(f"{BASE_URL}/people/{_ID}").mock(
        return_value=httpx.Response(200, json=_person_document())
    )
    loc_1 = respx.delete(f"{BASE_URL}/contact-locations/{_LOC_1}").mock(
        return_value=httpx.Response(204)
    )
    loc_2 = respx.delete(f"{BASE_URL}/contact-locations/{_LOC_2}").mock(
        return_value=httpx.Response(204)
    )
    party = respx.delete(f"{BASE_URL}/people/{_ID}").mock(return_value=httpx.Response(204))
    return preview, loc_1, loc_2, party


class TestDeletePerson:
    def test_is_registered(self) -> None:
        assert delete_person in TOOLS

    @respx.mock
    async def test_deletes_when_the_client_cannot_elicit(self, client: BackstopClient) -> None:
        preview, loc_1, loc_2, party = _mock_cascade()

        result = tool_model(
            await delete_person(
                ctx_no_elicitation_capability(),
                person=_PERSON.validate_python({"search_type": "people", "party_id": _ID}),
                resolve_party_query=make_resolve_party_query(client),
                delete_party_with_locations_command=make_command(client),
            ),
            DeletedPersonResponse,
        )

        assert result.id == _ID
        assert result.resource_type == "people"
        assert result.permanent is True
        assert result.deleted_location_ids == (_LOC_1, _LOC_2)
        assert preview.call_count == 1
        assert loc_1.call_count == 1
        assert loc_2.call_count == 1
        assert party.call_count == 1

    @respx.mock
    async def test_reads_the_person_then_deletes_after_elicit_accept(
        self, client: BackstopClient
    ) -> None:
        preview, _loc_1, _loc_2, party = _mock_cascade()
        prompts: list[str] = []

        async def elicit(
            *, message: str, response_type: object
        ) -> AcceptedElicitation[DeletionChoice]:
            _ = response_type
            prompts.append(message)
            return AcceptedElicitation(data=DeletionChoice(choice=DELETE))

        result = tool_model(
            await delete_person(
                as_context(FakeContext(elicit)),
                person=_PERSON.validate_python({"search_type": "people", "party_id": _ID}),
                resolve_party_query=make_resolve_party_query(client),
                delete_party_with_locations_command=make_command(client),
            ),
            DeletedPersonResponse,
        )

        assert result.id == _ID
        assert result.permanent is True
        assert preview.call_count == 2
        assert party.call_count == 1
        assert len(prompts) == 1
        assert _NAME in prompts[0]
        assert "2" in prompts[0]
        assert "contact locations" in prompts[0]

    @respx.mock
    async def test_confirmed_elicitation_deletes(self, client: BackstopClient) -> None:
        _preview, _loc_1, _loc_2, party = _mock_cascade()

        result = tool_model(
            await delete_person(
                ctx_accept(DeletionChoice(choice=DELETE)),
                person=_PERSON.validate_python({"search_type": "people", "party_id": _ID}),
                resolve_party_query=make_resolve_party_query(client),
                delete_party_with_locations_command=make_command(client),
            ),
            DeletedPersonResponse,
        )

        assert result.id == _ID
        assert party.call_count == 1

    @respx.mock
    async def test_declined_elicitation_does_not_write(self, client: BackstopClient) -> None:
        preview, loc_1, loc_2, party = _mock_cascade()

        with pytest.raises(ToolError, match="not confirmed") as raised:
            await delete_person(
                ctx_decline(),
                person=_PERSON.validate_python({"search_type": "people", "party_id": _ID}),
                resolve_party_query=make_resolve_party_query(client),
                delete_party_with_locations_command=make_command(client),
            )

        assert "Nothing was deleted" in str(raised.value)
        assert "Do not retry unless the user asks again" in str(raised.value)
        assert preview.call_count == 1
        assert loc_1.call_count == 0
        assert loc_2.call_count == 0
        assert party.call_count == 0
