"""`CreatePersonCommand`: POST payload shape, omit_empty, re-read phone."""

from collections.abc import AsyncGenerator

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from pydantic import TypeAdapter

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.org_people_writes import (
    CreatedPersonResponse,
    CreatePersonCommand,
    CreatePersonInput,
    get_create_person_command_factory,
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

_PERSON: TypeAdapter[CreatePersonInput] = TypeAdapter(CreatePersonInput)
_ID = "9001"
_REPRESENTATIVE_ID = "2967455"


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def _create(**payload: object) -> CreatePersonInput:
    return _PERSON.validate_python({"last_name": "Smith", "gender": "Female", **payload})


def make_command(
    client: BackstopClient,
    *,
    build_entity_link_util: BuildEntityLinkUtil | None = None,
) -> CreatePersonCommand:
    return get_create_person_command_factory(
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


def _person_document(
    *, status: int = 200, name: str | None = None, mobile_phone: str | None = None
) -> httpx.Response:
    attributes: dict[str, object] = {}
    if name is not None:
        attributes["name"] = name
    if mobile_phone is not None:
        attributes["mobilePhone"] = mobile_phone
    return httpx.Response(
        status,
        json={"data": {"id": _ID, "type": "people", "attributes": attributes}},
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


class TestCreatePersonCommand:
    @respx.mock
    async def test_create_person_sends_last_name_and_gender(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/people/{_ID}").mock(return_value=_person_document())
        route = respx.post(f"{BASE_URL}/people").mock(return_value=_person_document(status=201))

        await make_command(client).run(person=_create())

        body = recorded_json_bodies(route)[0]
        assert _attributes(body) == {"lastName": "Smith", "gender": "Female"}
        assert _data(body)["type"] == "people"

    @respx.mock
    async def test_create_person_omits_unsupplied_fields(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/people/{_ID}").mock(return_value=_person_document())
        route = respx.post(f"{BASE_URL}/people").mock(return_value=_person_document(status=201))

        await make_command(client).run(person=_create())

        body = recorded_json_bodies(route)[0]
        assert set(_attributes(body)) == {"lastName", "gender"}
        assert "relationships" not in _data(body)

    @respx.mock
    async def test_empty_category_ids_are_omitted(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/people/{_ID}").mock(return_value=_person_document())
        route = respx.post(f"{BASE_URL}/people").mock(return_value=_person_document(status=201))

        await make_command(client).run(person=_create(category_ids=[]))

        assert "relationships" not in _data(recorded_json_bodies(route)[0])

    @respx.mock
    async def test_created_values_come_from_the_reread(self, client: BackstopClient) -> None:
        route = respx.post(f"{BASE_URL}/people").mock(
            return_value=_person_document(
                status=201, name="Posted Name", mobile_phone="+1 555 0100"
            )
        )
        respx.get(f"{BASE_URL}/people/{_ID}").mock(
            return_value=_person_document(name="Smith", mobile_phone="555-0100")
        )

        result = await make_command(client).run(person=_create(mobile_phone="+1 555 0100"))

        assert _attributes(recorded_json_bodies(route)[0])["mobilePhone"] == "+1 555 0100"
        assert isinstance(result, CreatedPersonResponse)
        assert result.id == _ID
        assert result.resource_type == "people"
        assert result.name == "Smith"
        assert result.mobile_phone == "555-0100"
        assert result.url is None

    @respx.mock
    async def test_confirmation_carries_canonical_url(self, client: BackstopClient) -> None:
        respx.post(f"{BASE_URL}/people").mock(return_value=_person_document(status=201))
        respx.get(f"{BASE_URL}/people/{_ID}").mock(return_value=_person_document())

        result = await make_command(
            client,
            build_entity_link_util=BuildEntityLinkUtil(ui_base_url="https://tenant.example.test"),
        ).run(person=_create())

        assert result.url == (
            "https://tenant.example.test/backstop/crm/ManagePerson.action?display=&party_id=9001"
        )

    @respx.mock
    async def test_unknown_owner_login_does_not_post(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/system-users").mock(return_value=_users_page())
        post = respx.post(f"{BASE_URL}/people")

        with pytest.raises(ToolError, match="No Backstop system user"):
            await make_command(client).run(person=_create(owner_login="nobody"))

        assert post.call_count == 0

    @respx.mock
    async def test_owner_login_is_resolved_to_a_system_user_id(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/system-users").mock(return_value=_users_page())
        respx.get(f"{BASE_URL}/people/{_ID}").mock(return_value=_person_document())
        route = respx.post(f"{BASE_URL}/people").mock(return_value=_person_document(status=201))

        await make_command(client).run(person=_create(owner_login="jdoe"))

        representative = object_dict(
            _relationships(recorded_json_bodies(route)[0])["representative"]
        )
        assert object_dict(representative["data"]) == {
            "type": "system-users",
            "id": _REPRESENTATIVE_ID,
        }

    @respx.mock
    async def test_supplied_category_ids_are_sent(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/people/{_ID}").mock(return_value=_person_document())
        route = respx.post(f"{BASE_URL}/people").mock(return_value=_person_document(status=201))

        await make_command(client).run(person=_create(category_ids=["cat-1"]))

        assert object_dict(_relationships(recorded_json_bodies(route)[0])["categories"])[
            "data"
        ] == [{"type": "contact-categories", "id": "cat-1"}]
