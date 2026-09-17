"""`delete_person`: format a confirmation prompt, then delete unless elicitation was declined."""

from collections.abc import AsyncGenerator

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from mcp.types import ElicitRequestFormParams, ElicitResult, InputRequiredResult
from pydantic import TypeAdapter

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.elicitation_utils import (
    CONFIRM_RETRY_MESSAGE,
    DELETE,
    DELETION_INPUT_KEY,
    DeletionNeedsConfirmationResponse,
)
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
    ctx_deletion_answer,
    ctx_handshake_era,
    ctx_never_elicit,
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
    async def test_reads_the_person_then_asks_without_deleting(
        self, client: BackstopClient
    ) -> None:
        preview, loc_1, loc_2, party = _mock_cascade()

        result = await delete_person(
            ctx_never_elicit(),
            person=_PERSON.validate_python({"search_type": "people", "party_id": _ID}),
            resolve_party_query=make_resolve_party_query(client),
            delete_party_with_locations_command=make_command(client),
        )

        assert isinstance(result, InputRequiredResult)
        assert result.input_requests is not None
        params = result.input_requests[DELETION_INPUT_KEY].params
        assert isinstance(params, ElicitRequestFormParams)
        assert _NAME in params.message
        assert "2" in params.message
        assert "contact locations" in params.message
        assert preview.call_count == 1
        assert loc_1.call_count == 0
        assert loc_2.call_count == 0
        assert party.call_count == 0

    @respx.mock
    async def test_handshake_era_returns_needs_confirmation_without_deleting(
        self, client: BackstopClient
    ) -> None:
        preview, loc_1, loc_2, party = _mock_cascade()

        result = tool_model(
            await delete_person(
                ctx_handshake_era(),
                person=_PERSON.validate_python({"search_type": "people", "party_id": _ID}),
                resolve_party_query=make_resolve_party_query(client),
                delete_party_with_locations_command=make_command(client),
            ),
            DeletionNeedsConfirmationResponse,
        )

        assert result.status == "needs_confirmation"
        assert result.message == CONFIRM_RETRY_MESSAGE
        assert _NAME in result.preview
        assert preview.call_count == 1
        assert loc_1.call_count == 0
        assert loc_2.call_count == 0
        assert party.call_count == 0

    @respx.mock
    async def test_handshake_era_deletes_when_confirm_is_true(self, client: BackstopClient) -> None:
        preview, loc_1, loc_2, party = _mock_cascade()

        result = tool_model(
            await delete_person(
                ctx_handshake_era(),
                person=_PERSON.validate_python(
                    {"search_type": "people", "party_id": _ID, "confirm": True}
                ),
                resolve_party_query=make_resolve_party_query(client),
                delete_party_with_locations_command=make_command(client),
            ),
            DeletedPersonResponse,
        )

        assert result.id == _ID
        assert preview.call_count == 1
        assert loc_1.call_count == 1
        assert loc_2.call_count == 1
        assert party.call_count == 1

    @respx.mock
    async def test_confirmed_elicitation_deletes(self, client: BackstopClient) -> None:
        _preview, _loc_1, _loc_2, party = _mock_cascade()

        result = tool_model(
            await delete_person(
                ctx_deletion_answer(ElicitResult(action="accept", content={"choice": DELETE})),
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
                ctx_deletion_answer(ElicitResult(action="decline")),
                person=_PERSON.validate_python({"search_type": "people", "party_id": _ID}),
                resolve_party_query=make_resolve_party_query(client),
                delete_party_with_locations_command=make_command(client),
            )

        assert "Nothing was deleted" in str(raised.value)
        assert "Do not retry unless the user asks again" in str(raised.value)
        assert preview.call_count == 0
        assert loc_1.call_count == 0
        assert loc_2.call_count == 0
        assert party.call_count == 0

    @respx.mock
    async def test_deletes_the_resolved_collection(self, client: BackstopClient) -> None:
        contact_id = "c9"
        respx.get(f"{BASE_URL}/contacts/{contact_id}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "id": contact_id,
                        "type": "contacts",
                        "attributes": {"name": _NAME},
                        "relationships": {"contactLocations": {"data": []}},
                    },
                    "included": [],
                },
            )
        )
        party = respx.delete(f"{BASE_URL}/contacts/{contact_id}").mock(
            return_value=httpx.Response(204)
        )
        people = respx.delete(url__regex=rf"{BASE_URL}/people/\w+")

        result = tool_model(
            await delete_person(
                ctx_no_elicitation_capability(),
                person=_PERSON.validate_python({"search_type": "contacts", "party_id": contact_id}),
                resolve_party_query=make_resolve_party_query(client),
                delete_party_with_locations_command=make_command(client),
            ),
            DeletedPersonResponse,
        )

        assert result.id == contact_id
        assert result.resource_type == "contacts"
        assert party.call_count == 1
        assert people.call_count == 0
