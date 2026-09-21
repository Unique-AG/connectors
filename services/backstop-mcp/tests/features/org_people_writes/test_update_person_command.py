"""`UpdatePersonCommand`: PATCH payload shape, category append trap, re-read phone."""

from collections.abc import AsyncGenerator

import httpx
import pytest
import respx
from pydantic import TypeAdapter

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.org_people_writes import (
    UpdatedPersonResponse,
    UpdatePersonCommand,
    UpdatePersonInput,
    get_modify_contact_location_command_factory,
    get_update_person_command_factory,
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

_PERSON: TypeAdapter[UpdatePersonInput] = TypeAdapter(UpdatePersonInput)
_ID = "27871657"
_REPRESENTATIVE_ID = "2967455"


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def _update(**payload: object) -> UpdatePersonInput:
    return _PERSON.validate_python({"party_id": _ID, **payload})


def make_command(
    client: BackstopClient,
    *,
    build_entity_link_util: BuildEntityLinkUtil | None = None,
) -> UpdatePersonCommand:
    return get_update_person_command_factory(
        client,
        system_users_service=system_users_service(client),
        modify_contact_location_command=get_modify_contact_location_command_factory(client),
        build_entity_link_util=build_entity_link_util or BuildEntityLinkUtil(ui_base_url=None),
    )


def _data(body: dict[str, object]) -> dict[str, object]:
    return object_dict(body["data"])


def _attributes(body: dict[str, object]) -> dict[str, object]:
    return object_dict(_data(body)["attributes"])


def _relationships(body: dict[str, object]) -> dict[str, object]:
    return object_dict(_data(body)["relationships"])


def _person_document(
    *,
    mobile_phone: str | None = None,
    attributes: dict[str, object] | None = None,
) -> httpx.Response:
    payload: dict[str, object] = {} if attributes is None else dict(attributes)
    if mobile_phone is not None:
        payload["mobilePhone"] = mobile_phone
    return httpx.Response(
        200,
        json={"data": {"id": _ID, "type": "people", "attributes": payload}},
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


class TestUpdatePersonCommand:
    @respx.mock
    async def test_only_the_changed_attribute_is_sent(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/people/{_ID}").mock(return_value=_person_document())
        route = respx.patch(f"{BASE_URL}/people/{_ID}").mock(return_value=_person_document())

        await make_command(client).run(
            person=_update(job_title="Managing Director"), party_id=_ID, search_type="people"
        )

        body = recorded_json_bodies(route)[0]
        assert _attributes(body) == {"jobTitle": "Managing Director"}
        assert "relationships" not in _data(body)

    @respx.mock
    async def test_reported_value_comes_from_the_reread_not_the_request(
        self, client: BackstopClient
    ) -> None:
        respx.patch(f"{BASE_URL}/people/{_ID}").mock(
            return_value=_person_document(mobile_phone="+1 555 0100")
        )
        respx.get(f"{BASE_URL}/people/{_ID}").mock(
            return_value=_person_document(mobile_phone="555-0100")
        )

        result = await make_command(client).run(
            person=_update(mobile_phone="+1 555 0100"), party_id=_ID, search_type="people"
        )

        assert isinstance(result, UpdatedPersonResponse)
        assert result.mobile_phone == "555-0100"
        assert result.person.mobile_phone == "555-0100"
        assert result.url is None

    @respx.mock
    async def test_confirmation_carries_canonical_url(self, client: BackstopClient) -> None:
        respx.patch(f"{BASE_URL}/people/{_ID}").mock(return_value=_person_document())
        respx.get(f"{BASE_URL}/people/{_ID}").mock(return_value=_person_document())

        result = await make_command(
            client,
            build_entity_link_util=BuildEntityLinkUtil(ui_base_url="https://tenant.example.test"),
        ).run(person=_update(job_title="Managing Director"), party_id=_ID, search_type="people")

        assert result.url == (
            f"https://tenant.example.test/backstop/crm/ManagePerson.action?display=&party_id={_ID}"
        )

    @respx.mock
    async def test_reread_publishes_top_level_fields_as_snake_case(
        self, client: BackstopClient
    ) -> None:
        respx.patch(f"{BASE_URL}/people/{_ID}").mock(return_value=_person_document())
        respx.get(f"{BASE_URL}/people/{_ID}").mock(
            return_value=_person_document(
                attributes={
                    "name": "Doe, Jane",
                    "firstName": "Jane",
                    "lastName": "Doe",
                    "jobTitle": "Managing Director",
                    "email": "jane@example.com",
                    "isEmployee": False,
                    "isKeyEmployee": True,
                    "department": "",
                    "landingPageUrl": "https://example.com/jane",
                }
            )
        )

        result = await make_command(client).run(
            person=_update(job_title="Managing Director"), party_id=_ID, search_type="people"
        )

        assert isinstance(result, UpdatedPersonResponse)
        assert result.person.first_name == "Jane"
        assert result.person.last_name == "Doe"
        assert result.person.job_title == "Managing Director"
        assert result.person.email == "jane@example.com"
        assert result.person.is_employee is False
        assert result.person.is_key_employee is True
        assert result.person.landing_page_url == "https://example.com/jane"
        dumped = result.person.model_dump(exclude_none=True)
        assert "department" not in dumped
        assert "firstName" not in dumped
        assert "jobTitle" not in dumped
        assert "isKeyEmployee" not in dumped

    @respx.mock
    async def test_add_categories_appends_and_replace_categories_clears_first(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/people/{_ID}").mock(return_value=_person_document())
        route = respx.patch(f"{BASE_URL}/people/{_ID}").mock(return_value=_person_document())

        await make_command(client).run(
            person=_update(add_category_ids=["cat-1"]), party_id=_ID, search_type="people"
        )
        add_count = route.call_count
        await make_command(client).run(
            person=_update(replace_category_ids=["cat-2"]), party_id=_ID, search_type="people"
        )
        bodies = recorded_json_bodies(route)
        assert object_dict(_relationships(bodies[0])["categories"])["data"] == [
            {"type": "contact-categories", "id": "cat-1"}
        ]
        assert add_count == 1
        replace_bodies = bodies[add_count:]
        assert len(replace_bodies) == 2
        assert object_dict(_relationships(replace_bodies[0])["categories"])["data"] == []
        assert object_dict(_relationships(replace_bodies[1])["categories"])["data"] == [
            {"type": "contact-categories", "id": "cat-2"}
        ]

    @respx.mock
    async def test_owner_login_is_resolved_to_a_system_user_id(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/system-users").mock(return_value=_users_page())
        respx.get(f"{BASE_URL}/people/{_ID}").mock(return_value=_person_document())
        route = respx.patch(f"{BASE_URL}/people/{_ID}").mock(return_value=_person_document())

        await make_command(client).run(
            person=_update(owner_login="jdoe"), party_id=_ID, search_type="people"
        )

        representative = object_dict(
            _relationships(recorded_json_bodies(route)[0])["representative"]
        )
        assert object_dict(representative["data"]) == {
            "type": "system-users",
            "id": _REPRESENTATIVE_ID,
        }

    @respx.mock
    async def test_a_location_block_is_threaded_through_to_the_location_write(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/people/{_ID}").mock(return_value=_person_document())
        respx.patch(f"{BASE_URL}/people/{_ID}").mock(return_value=_person_document())
        location = respx.post(f"{BASE_URL}/contact-locations").mock(
            return_value=httpx.Response(
                201,
                json={"data": {"id": "loc-1", "type": "contact-locations", "attributes": {}}},
            )
        )

        result = await make_command(client).run(
            person=_update(
                job_title="Managing Director",
                locations=[{"location_title": "Office", "city": "Chicago"}],
            ),
            party_id=_ID,
            search_type="people",
        )

        assert location.call_count == 1
        assert result.location_ids == ("loc-1",)
        contact = object_dict(
            object_dict(
                object_dict(_data(recorded_json_bodies(location)[0])["relationships"])["contact"]
            )["data"]
        )
        assert contact == {"type": "contacts", "id": _ID}

    @respx.mock
    async def test_a_delete_location_id_is_threaded_through_to_the_delete(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/people/{_ID}").mock(return_value=_person_document())
        deletion = respx.delete(f"{BASE_URL}/contact-locations/loc-9").mock(
            return_value=httpx.Response(204, content=b"")
        )

        result = await make_command(client).run(
            person=_update(delete_location_ids=["loc-9"]), party_id=_ID, search_type="people"
        )

        assert deletion.call_count == 1
        assert result.location_ids == ()

    @respx.mock
    async def test_patches_the_resolved_collection(self, client: BackstopClient) -> None:
        contact_id = "c9"
        respx.get(f"{BASE_URL}/contacts/{contact_id}").mock(
            return_value=httpx.Response(
                200,
                json={"data": {"id": contact_id, "type": "contacts", "attributes": {}}},
            )
        )
        route = respx.patch(f"{BASE_URL}/contacts/{contact_id}").mock(
            return_value=httpx.Response(
                200,
                json={"data": {"id": contact_id, "type": "contacts", "attributes": {}}},
            )
        )
        people = respx.patch(url__regex=rf"{BASE_URL}/people/\w+")

        result = await make_command(client).run(
            person=_PERSON.validate_python({"party_id": contact_id, "job_title": "Director"}),
            party_id=contact_id,
            search_type="contacts",
        )

        assert result.resource_type == "contacts"
        assert route.call_count == 1
        assert people.call_count == 0
        assert _data(recorded_json_bodies(route)[0])["type"] == "contacts"
