"""POST `/people`, then re-read the created record."""

import logging
from urllib.parse import quote

from opentelemetry import trace

from backstop_mcp.backstop_client import (
    BackstopApiSingleResourceDocument,
    BackstopClient,
    json_api_create,
    omit_none_values,
)
from backstop_mcp.features.org_people_writes.api_responses import PersonWriteAttributes
from backstop_mcp.features.org_people_writes.commands._contact_attributes import (
    person_attributes,
    person_relationships,
)
from backstop_mcp.features.org_people_writes.create_person_input import CreatePersonInput
from backstop_mcp.features.org_people_writes.responses import CreatedPersonResponse
from backstop_mcp.features.system_users import SystemUsersService

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

_Document = BackstopApiSingleResourceDocument[PersonWriteAttributes]
_RESOURCE_TYPE = "people"


class CreatePersonCommand:
    """Create one person via `POST /people`, then report the re-read."""

    def __init__(
        self,
        *,
        client: BackstopClient,
        system_users_service: SystemUsersService,
    ) -> None:
        self._client: BackstopClient = client
        self._system_users_service: SystemUsersService = system_users_service

    async def run(self, *, person: CreatePersonInput) -> CreatedPersonResponse:
        with _tracer.start_as_current_span("org_people_writes.command.create_person"):
            owner = await self._system_users_service.resolve_relationship(person.owner_login)
            attributes = omit_none_values(person_attributes(person))
            relationships = omit_none_values(
                person_relationships(person, owner=owner, omit_empty=True)
            )
            created = await self._client.post(
                f"/{_RESOURCE_TYPE}",
                schema=_Document,
                json=json_api_create(
                    resource_type=_RESOURCE_TYPE,
                    attributes=attributes,
                    relationships=relationships or None,
                ),
            )
            created_id = created.data.id
            written = await self._client.get(
                f"/{_RESOURCE_TYPE}/{quote(created_id, safe='')}", schema=_Document
            )
            logger.info("org_people_writes.person.created", extra={"id": created_id})
            return CreatedPersonResponse(
                id=created_id,
                resource_type=_RESOURCE_TYPE,
                name=written.data.attributes.name,
                mobile_phone=written.data.attributes.mobile_phone,
            )
