"""`delete_organization`: format a confirmation prompt, then delete unless elicitation
was declined.
"""

from collections.abc import AsyncGenerator

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from mcp.types import ElicitRequestFormParams, ElicitResult, InputRequiredResult
from pydantic import TypeAdapter

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.elicitation_utils import (
    DELETE,
    DELETION_INPUT_KEY,
    DeletionNeedsConfirmationResponse,
)
from backstop_mcp.features.org_people_writes import (
    DeletedOrganizationResponse,
    DeleteOrganizationInput,
    DeletePartyWithLocationsCommand,
    get_delete_party_with_locations_command_factory,
    get_modify_contact_location_command_factory,
)
from backstop_mcp.features.org_people_writes.tools.delete_organization import delete_organization
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

_ORGANIZATION: TypeAdapter[DeleteOrganizationInput] = TypeAdapter(DeleteOrganizationInput)
_ID = "org-1"
_NAME = "Acme Advisors"
_LOC_1 = "loc-1"


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


def _organization_document(*, location_ids: tuple[str, ...] = (_LOC_1,)) -> dict[str, object]:
    return {
        "data": {
            "id": _ID,
            "type": "organizations",
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
                "attributes": {"locationTitle": f"HQ {loc_id}"},
            }
            for loc_id in location_ids
        ],
    }


def _mock_cascade() -> tuple[respx.Route, respx.Route, respx.Route]:
    preview = respx.get(f"{BASE_URL}/organizations/{_ID}").mock(
        return_value=httpx.Response(200, json=_organization_document())
    )
    location = respx.delete(f"{BASE_URL}/contact-locations/{_LOC_1}").mock(
        return_value=httpx.Response(204)
    )
    party = respx.delete(f"{BASE_URL}/organizations/{_ID}").mock(return_value=httpx.Response(204))
    return preview, location, party


class TestDeleteOrganization:
    def test_is_registered(self) -> None:
        assert delete_organization in TOOLS

    @respx.mock
    async def test_deletes_when_the_client_cannot_elicit(self, client: BackstopClient) -> None:
        preview, location, party = _mock_cascade()

        result = tool_model(
            await delete_organization(
                ctx_no_elicitation_capability(),
                organization=_ORGANIZATION.validate_python(
                    {"search_type": "organizations", "party_id": _ID}
                ),
                resolve_party_query=make_resolve_party_query(client),
                delete_party_with_locations_command=make_command(client),
            ),
            DeletedOrganizationResponse,
        )

        assert result.id == _ID
        assert result.resource_type == "organizations"
        assert result.permanent is True
        assert result.deleted_location_ids == (_LOC_1,)
        assert preview.call_count == 1
        assert location.call_count == 1
        assert party.call_count == 1

    @respx.mock
    async def test_reads_the_organization_then_asks_without_deleting(
        self, client: BackstopClient
    ) -> None:
        preview, location, party = _mock_cascade()

        result = await delete_organization(
            ctx_never_elicit(),
            organization=_ORGANIZATION.validate_python(
                {"search_type": "organizations", "party_id": _ID}
            ),
            resolve_party_query=make_resolve_party_query(client),
            delete_party_with_locations_command=make_command(client),
        )

        assert isinstance(result, InputRequiredResult)
        assert result.input_requests is not None
        params = result.input_requests[DELETION_INPUT_KEY].params
        assert isinstance(params, ElicitRequestFormParams)
        assert _NAME in params.message
        assert "1" in params.message
        assert "contact location" in params.message
        assert preview.call_count == 1
        assert location.call_count == 0
        assert party.call_count == 0

    @respx.mock
    async def test_handshake_era_returns_needs_confirmation_without_deleting(
        self, client: BackstopClient
    ) -> None:
        preview, location, party = _mock_cascade()

        result = tool_model(
            await delete_organization(
                ctx_handshake_era(),
                organization=_ORGANIZATION.validate_python(
                    {"search_type": "organizations", "party_id": _ID}
                ),
                resolve_party_query=make_resolve_party_query(client),
                delete_party_with_locations_command=make_command(client),
            ),
            DeletionNeedsConfirmationResponse,
        )

        assert result.status == "needs_confirmation"
        assert _NAME in result.preview
        assert preview.call_count == 1
        assert location.call_count == 0
        assert party.call_count == 0

    @respx.mock
    async def test_handshake_era_deletes_when_confirm_is_true(self, client: BackstopClient) -> None:
        _preview, location, party = _mock_cascade()

        result = tool_model(
            await delete_organization(
                ctx_handshake_era(),
                organization=_ORGANIZATION.validate_python(
                    {"search_type": "organizations", "party_id": _ID, "confirm": True}
                ),
                resolve_party_query=make_resolve_party_query(client),
                delete_party_with_locations_command=make_command(client),
            ),
            DeletedOrganizationResponse,
        )

        assert result.id == _ID
        assert location.call_count == 1
        assert party.call_count == 1

    @respx.mock
    async def test_confirmed_elicitation_deletes(self, client: BackstopClient) -> None:
        _preview, _location, party = _mock_cascade()

        result = tool_model(
            await delete_organization(
                ctx_deletion_answer(ElicitResult(action="accept", content={"choice": DELETE})),
                organization=_ORGANIZATION.validate_python(
                    {"search_type": "organizations", "party_id": _ID}
                ),
                resolve_party_query=make_resolve_party_query(client),
                delete_party_with_locations_command=make_command(client),
            ),
            DeletedOrganizationResponse,
        )

        assert result.id == _ID
        assert party.call_count == 1

    @respx.mock
    async def test_declined_elicitation_does_not_write(self, client: BackstopClient) -> None:
        _preview, location, party = _mock_cascade()

        with pytest.raises(ToolError, match="not confirmed") as raised:
            await delete_organization(
                ctx_deletion_answer(ElicitResult(action="decline")),
                organization=_ORGANIZATION.validate_python(
                    {"search_type": "organizations", "party_id": _ID}
                ),
                resolve_party_query=make_resolve_party_query(client),
                delete_party_with_locations_command=make_command(client),
            )

        assert "Nothing was deleted" in str(raised.value)
        assert location.call_count == 0
        assert party.call_count == 0
