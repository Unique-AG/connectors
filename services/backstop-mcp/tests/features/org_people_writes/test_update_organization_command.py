"""`UpdateOrganizationCommand`: PATCH payload shape and category append trap."""

from collections.abc import AsyncGenerator

import httpx
import pytest
import respx
from pydantic import TypeAdapter

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.org_people_writes import (
    UpdateOrganizationCommand,
    UpdateOrganizationInput,
    get_modify_contact_location_command_factory,
    get_update_organization_command_factory,
)
from tests.helpers import (
    BASE_URL,
    client_factory,
    credential,
    recorded_json_bodies,
    system_users_service,
)
from tests.server.tools.helpers import object_dict

_ORG: TypeAdapter[UpdateOrganizationInput] = TypeAdapter(UpdateOrganizationInput)
_ID = "1001"


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def _update(**payload: object) -> UpdateOrganizationInput:
    return _ORG.validate_python({"party_id": _ID, **payload})


def make_command(client: BackstopClient) -> UpdateOrganizationCommand:
    return get_update_organization_command_factory(
        client,
        system_users_service=system_users_service(client),
        modify_contact_location_command=get_modify_contact_location_command_factory(client),
    )


def _data(body: dict[str, object]) -> dict[str, object]:
    return object_dict(body["data"])


def _attributes(body: dict[str, object]) -> dict[str, object]:
    return object_dict(_data(body)["attributes"])


def _relationships(body: dict[str, object]) -> dict[str, object]:
    return object_dict(_data(body)["relationships"])


def _org_document() -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": {"id": _ID, "type": "organizations", "attributes": {"name": "Acme"}}},
    )


class TestUpdateOrganizationCommand:
    @respx.mock
    async def test_only_the_changed_attribute_is_sent(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/organizations/{_ID}").mock(return_value=_org_document())
        route = respx.patch(f"{BASE_URL}/organizations/{_ID}").mock(return_value=_org_document())

        await make_command(client).run(
            new_organization_fields=_update(website="https://example.com"), party_id=_ID
        )

        body = recorded_json_bodies(route)[0]
        assert _attributes(body) == {"website": "https://example.com"}
        assert "relationships" not in _data(body)

    @respx.mock
    async def test_add_categories_appends_and_replace_categories_clears_first(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/organizations/{_ID}").mock(return_value=_org_document())
        route = respx.patch(f"{BASE_URL}/organizations/{_ID}").mock(return_value=_org_document())

        await make_command(client).run(
            new_organization_fields=_update(add_category_ids=["cat-1"]), party_id=_ID
        )
        add_count = route.call_count
        await make_command(client).run(
            new_organization_fields=_update(replace_category_ids=["cat-2"]), party_id=_ID
        )
        bodies = recorded_json_bodies(route)
        add_bodies = bodies[:add_count]
        replace_bodies = bodies[add_count:]
        assert len(add_bodies) == 1
        assert object_dict(_relationships(add_bodies[0])["categories"])["data"] == [
            {"type": "contact-categories", "id": "cat-1"}
        ]
        assert len(replace_bodies) == 2
        assert object_dict(_relationships(replace_bodies[0])["categories"])["data"] == []
        assert object_dict(_relationships(replace_bodies[1])["categories"])["data"] == [
            {"type": "contact-categories", "id": "cat-2"}
        ]
