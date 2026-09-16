"""PATCH `/{search_type}/{id}`, then optional `/contact-locations` writes."""

import logging
from urllib.parse import quote

from opentelemetry import trace

from backstop_mcp.backstop_client import (
    BackstopApiSingleResourceDocument,
    BackstopClient,
    json_api_update,
    omit_none_values,
    relationship_data,
)
from backstop_mcp.features.org_people_writes.api_responses import PersonWriteAttributes
from backstop_mcp.features.org_people_writes.commands._contact_attributes import (
    person_attributes,
    person_relationships,
)
from backstop_mcp.features.org_people_writes.commands.delete_party_with_locations_command import (
    PersonCollection,
)
from backstop_mcp.features.org_people_writes.commands.modify_contact_location_command import (
    ModifyContactLocationCommand,
)
from backstop_mcp.features.org_people_writes.responses import UpdatedPersonResponse
from backstop_mcp.features.org_people_writes.update_person_input import UpdatePersonInput
from backstop_mcp.features.system_users import SystemUsersService

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

_Document = BackstopApiSingleResourceDocument[PersonWriteAttributes]


class UpdatePersonCommand:
    """Update one person via `PATCH /{search_type}/{id}`, then apply location writes."""

    def __init__(
        self,
        *,
        client: BackstopClient,
        system_users_service: SystemUsersService,
        modify_contact_location_command: ModifyContactLocationCommand,
    ) -> None:
        self._client: BackstopClient = client
        self._system_users_service: SystemUsersService = system_users_service
        self._modify_contact_location_command: ModifyContactLocationCommand = (
            modify_contact_location_command
        )

    async def run(
        self, *, person: UpdatePersonInput, party_id: str, search_type: PersonCollection
    ) -> UpdatedPersonResponse:
        with _tracer.start_as_current_span("org_people_writes.command.update_person") as span:
            span.set_attribute("party_id", party_id)
            span.set_attribute("search_type", search_type)
            owner = await self._system_users_service.resolve_relationship(person.owner_login)
            await self._patch(person, party_id=party_id, search_type=search_type, owner=owner)
            location_id = await self._modify_contact_location_command.run(
                party_id=party_id,
                location=person.location,
                delete_location_id=person.delete_location_id,
            )
            written = await self._read(party_id, search_type=search_type)
            logger.info(
                "org_people_writes.person.updated",
                extra={"id": party_id, "search_type": search_type, "location_id": location_id},
            )
            return UpdatedPersonResponse(
                id=party_id,
                resource_type=search_type,
                mobile_phone=written.data.attributes.mobile_phone,
                location_id=location_id,
            )

    async def _read(self, party_id: str, *, search_type: PersonCollection) -> _Document:
        path = f"/{search_type}/{quote(party_id, safe='')}"
        return await self._client.get(path, schema=_Document)

    async def _patch(
        self,
        person: UpdatePersonInput,
        *,
        party_id: str,
        search_type: PersonCollection,
        owner: dict[str, object] | None,
    ) -> None:
        attributes = omit_none_values(person_attributes(person))
        relationships = omit_none_values(
            person_relationships(person, owner=owner, omit_empty=False)
        )
        # A to-many PATCH appends; `data: []` clears, then a second PATCH adds replacements.
        if person.replace_category_ids is not None:
            relationships["categories"] = relationship_data("contact-categories", ())
        if not attributes and not relationships:
            return
        path = f"/{search_type}/{quote(party_id, safe='')}"
        await self._client.patch(
            path,
            schema=_Document,
            json=json_api_update(
                resource_type=search_type,
                resource_id=party_id,
                attributes=attributes,
                relationships=relationships or None,
            ),
        )
        if person.replace_category_ids:
            await self._client.patch(
                path,
                schema=_Document,
                json=json_api_update(
                    resource_type=search_type,
                    resource_id=party_id,
                    attributes={},
                    relationships={
                        "categories": relationship_data(
                            "contact-categories", person.replace_category_ids
                        )
                    },
                ),
            )
