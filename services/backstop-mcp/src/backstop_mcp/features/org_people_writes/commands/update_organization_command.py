"""PATCH `/organizations/{id}`, then optional `/contact-locations` writes.

Re-reads the organization so the tool can publish the same top-level scalars as
`get_organization`.
"""

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
from backstop_mcp.features.org_people import OrganizationAttributes, OrganizationRecordResponse
from backstop_mcp.features.org_people_writes.api_responses import OrganizationWriteAttributes
from backstop_mcp.features.org_people_writes.commands._contact_attributes import (
    organization_attributes,
    organization_relationships,
)
from backstop_mcp.features.org_people_writes.commands.modify_contact_location_command import (
    ModifyContactLocationCommand,
)
from backstop_mcp.features.org_people_writes.responses import UpdatedOrganizationResponse
from backstop_mcp.features.org_people_writes.update_organization_input import (
    UpdateOrganizationInput,
)
from backstop_mcp.features.system_users import SystemUsersService
from backstop_mcp.features.ui_links import BuildEntityLinkUtil, OrganizationLinkTarget

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

_PatchDocument = BackstopApiSingleResourceDocument[OrganizationWriteAttributes]
_ReadDocument = BackstopApiSingleResourceDocument[OrganizationAttributes]
_RESOURCE_TYPE = "organizations"


class UpdateOrganizationCommand:
    """Update one organization via `PATCH /organizations/{id}`, then apply location writes."""

    def __init__(
        self,
        *,
        client: BackstopClient,
        system_users_service: SystemUsersService,
        modify_contact_location_command: ModifyContactLocationCommand,
        build_entity_link_util: BuildEntityLinkUtil,
    ) -> None:
        self._client: BackstopClient = client
        self._system_users_service: SystemUsersService = system_users_service
        self._modify_contact_location_command: ModifyContactLocationCommand = (
            modify_contact_location_command
        )
        self._build_entity_link_util: BuildEntityLinkUtil = build_entity_link_util

    async def run(
        self, *, new_organization_fields: UpdateOrganizationInput, party_id: str
    ) -> UpdatedOrganizationResponse:
        with _tracer.start_as_current_span("org_people_writes.command.update_organization") as span:
            span.set_attribute("party_id", party_id)
            owner = await self._system_users_service.resolve_relationship(
                new_organization_fields.owner_login
            )
            await self._patch(new_organization_fields, party_id=party_id, owner=owner)
            location_ids = await self._modify_contact_location_command.run(
                party_id=party_id,
                locations=new_organization_fields.locations or (),
                delete_location_ids=new_organization_fields.delete_location_ids or (),
            )
            written = await self._read(party_id)
            logger.info(
                "org_people_writes.organization.updated",
                extra={"id": party_id, "location_ids": location_ids},
            )
            return UpdatedOrganizationResponse(
                id=party_id,
                resource_type=_RESOURCE_TYPE,
                organization=OrganizationRecordResponse.from_attributes(written.data.attributes),
                location_ids=location_ids,
                url=self._build_entity_link_util.canonical_url(
                    target=OrganizationLinkTarget(party_id=party_id)
                ),
            )

    async def _read(self, party_id: str) -> _ReadDocument:
        path = f"/{_RESOURCE_TYPE}/{quote(party_id, safe='')}"
        return await self._client.get(path, schema=_ReadDocument)

    async def _patch(
        self,
        new_organization_fields: UpdateOrganizationInput,
        *,
        party_id: str,
        owner: dict[str, object] | None,
    ) -> None:
        attributes = omit_none_values(organization_attributes(new_organization_fields))
        relationships = omit_none_values(
            organization_relationships(new_organization_fields, owner=owner, omit_empty=False)
        )
        # A to-many PATCH appends; `data: []` clears, then a second PATCH adds replacements.
        if new_organization_fields.replace_category_ids is not None:
            relationships["categories"] = relationship_data("contact-categories", ())
        if not attributes and not relationships:
            return
        path = f"/{_RESOURCE_TYPE}/{quote(party_id, safe='')}"
        await self._client.patch(
            path,
            schema=_PatchDocument,
            json=json_api_update(
                resource_type=_RESOURCE_TYPE,
                resource_id=party_id,
                attributes=attributes,
                relationships=relationships or None,
            ),
        )
        if new_organization_fields.replace_category_ids:
            await self._client.patch(
                path,
                schema=_PatchDocument,
                json=json_api_update(
                    resource_type=_RESOURCE_TYPE,
                    resource_id=party_id,
                    attributes={},
                    relationships={
                        "categories": relationship_data(
                            "contact-categories", new_organization_fields.replace_category_ids
                        )
                    },
                ),
            )
