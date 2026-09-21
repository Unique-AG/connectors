"""`CreateOrganizationCommand`: POST payload shape, omit_empty, re-read name."""

from collections.abc import AsyncGenerator

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from pydantic import TypeAdapter

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.org_people_writes import (
    CreatedOrganizationResponse,
    CreateOrganizationCommand,
    CreateOrganizationInput,
    get_create_organization_command_factory,
)
from backstop_mcp.features.ui_links import BuildEntityLinkUtil
from tests.helpers import (
    BASE_URL,
    client_factory,
    credential,
    recorded_json_bodies,
    system_users_service,
)
from tests.server.tools.helpers import object_dict

_ORG: TypeAdapter[CreateOrganizationInput] = TypeAdapter(CreateOrganizationInput)
_ID = "8001"
_REPRESENTATIVE_ID = "2967455"


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def _create(**payload: object) -> CreateOrganizationInput:
    return _ORG.validate_python({"name": "Acme", **payload})


def make_command(
    client: BackstopClient,
    *,
    build_entity_link_util: BuildEntityLinkUtil | None = None,
) -> CreateOrganizationCommand:
    return get_create_organization_command_factory(
        client,
        system_users_service=system_users_service(client),
        build_entity_link_util=build_entity_link_util or BuildEntityLinkUtil(ui_base_url=None),
    )


def _data(body: dict[str, object]) -> dict[str, object]:
    return object_dict(body["data"])


def _attributes(body: dict[str, object]) -> dict[str, object]:
    return object_dict(_data(body)["attributes"])


def _relationships(body: dict[str, object]) -> dict[str, object]:
    return object_dict(_data(body)["relationships"])


def _org_document(*, status: int = 200, name: str = "Acme") -> httpx.Response:
    return httpx.Response(
        status,
        json={"data": {"id": _ID, "type": "organizations", "attributes": {"name": name}}},
    )


def _users_page() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": [
                {
                    "id": _REPRESENTATIVE_ID,
                    "type": "system-users",
                    "attributes": {"name": "Jane Doe", "userName": "jdoe"},
                }
            ],
            "links": {"next": None},
        },
    )


class TestCreateOrganizationCommand:
    @respx.mock
    async def test_create_organization_sends_name(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/organizations/{_ID}").mock(return_value=_org_document())
        route = respx.post(f"{BASE_URL}/organizations").mock(return_value=_org_document(status=201))

        await make_command(client).run(organization=_create())

        body = recorded_json_bodies(route)[0]
        assert _attributes(body) == {"name": "Acme"}
        assert _data(body)["type"] == "organizations"

    @respx.mock
    async def test_create_organization_omits_unsupplied_fields(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/organizations/{_ID}").mock(return_value=_org_document())
        route = respx.post(f"{BASE_URL}/organizations").mock(return_value=_org_document(status=201))

        await make_command(client).run(organization=_create())

        body = recorded_json_bodies(route)[0]
        assert set(_attributes(body)) == {"name"}
        assert "relationships" not in _data(body)

    @respx.mock
    async def test_empty_category_ids_are_omitted(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/organizations/{_ID}").mock(return_value=_org_document())
        route = respx.post(f"{BASE_URL}/organizations").mock(return_value=_org_document(status=201))

        await make_command(client).run(organization=_create(category_ids=[]))

        assert "relationships" not in _data(recorded_json_bodies(route)[0])

    @respx.mock
    async def test_created_values_come_from_the_reread(self, client: BackstopClient) -> None:
        respx.post(f"{BASE_URL}/organizations").mock(
            return_value=_org_document(status=201, name="Posted Name")
        )
        respx.get(f"{BASE_URL}/organizations/{_ID}").mock(
            return_value=_org_document(name="Acme Advisors")
        )

        result = await make_command(client).run(organization=_create(name="Acme"))

        assert isinstance(result, CreatedOrganizationResponse)
        assert result.id == _ID
        assert result.resource_type == "organizations"
        assert result.name == "Acme Advisors"
        assert result.url is None

    @respx.mock
    async def test_confirmation_carries_canonical_url(self, client: BackstopClient) -> None:
        respx.post(f"{BASE_URL}/organizations").mock(return_value=_org_document(status=201))
        respx.get(f"{BASE_URL}/organizations/{_ID}").mock(return_value=_org_document())

        result = await make_command(
            client,
            build_entity_link_util=BuildEntityLinkUtil(ui_base_url="https://tenant.example.test"),
        ).run(organization=_create())

        assert result.url == (
            "https://tenant.example.test/backstop/crm/ManageOrganization.action"
            "?display=&party_id=8001"
        )

    @respx.mock
    async def test_unknown_owner_login_does_not_post(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/system-users").mock(return_value=_users_page())
        post = respx.post(f"{BASE_URL}/organizations")

        with pytest.raises(ToolError, match="No Backstop system user"):
            await make_command(client).run(organization=_create(owner_login="nobody"))

        assert post.call_count == 0
