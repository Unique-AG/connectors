"""POST `/organizations`, then re-read the created record."""

import logging
from urllib.parse import quote

from opentelemetry import trace

from backstop_mcp.backstop_client import (
    BackstopApiSingleResourceDocument,
    BackstopClient,
    json_api_create,
    omit_none_values,
)
from backstop_mcp.features.org_people_writes.api_responses import OrganizationWriteAttributes
from backstop_mcp.features.org_people_writes.commands._contact_attributes import (
    organization_attributes,
    organization_relationships,
)
from backstop_mcp.features.org_people_writes.create_organization_input import (
    CreateOrganizationInput,
)
from backstop_mcp.features.org_people_writes.responses import CreatedOrganizationResponse
from backstop_mcp.features.system_users import SystemUsersService
from backstop_mcp.features.ui_links import BuildEntityLinkUtil, OrganizationLinkTarget

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

_Document = BackstopApiSingleResourceDocument[OrganizationWriteAttributes]
_RESOURCE_TYPE = "organizations"


class CreateOrganizationCommand:
    """Create one organization via `POST /organizations`, then report the re-read."""

    def __init__(
        self,
        *,
        client: BackstopClient,
        system_users_service: SystemUsersService,
        build_entity_link_util: BuildEntityLinkUtil,
    ) -> None:
        self._client: BackstopClient = client
        self._system_users_service: SystemUsersService = system_users_service
        self._build_entity_link_util: BuildEntityLinkUtil = build_entity_link_util

    async def run(self, *, organization: CreateOrganizationInput) -> CreatedOrganizationResponse:
        with _tracer.start_as_current_span("org_people_writes.command.create_organization"):
            owner = await self._system_users_service.resolve_relationship(organization.owner_login)
            attributes = omit_none_values(organization_attributes(organization))
            relationships = omit_none_values(
                organization_relationships(organization, owner=owner, omit_empty=True)
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
            logger.info("org_people_writes.organization.created", extra={"id": created_id})
            return CreatedOrganizationResponse(
                id=created_id,
                resource_type=_RESOURCE_TYPE,
                name=written.data.attributes.name,
                url=self._build_entity_link_util.canonical_url(
                    target=OrganizationLinkTarget(party_id=created_id)
                ),
            )
