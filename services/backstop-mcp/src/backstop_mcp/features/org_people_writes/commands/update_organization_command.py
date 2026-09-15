"""PATCH `/organizations/{id}`, then optional `/contact-locations` writes.

No re-read, unlike `update_person`: Backstop rewrites phone numbers, and an organization
has no phone attribute here.
"""

import logging
from urllib.parse import quote

from opentelemetry import trace

from backstop_mcp.backstop_client import (
    BackstopApiSingleResourceDocument,
    BackstopClient,
    isoformat,
    json_api_update,
    omit_none_values,
    relationship_data,
    relationship_to_one,
)
from backstop_mcp.features.org_people_writes.api_responses import OrganizationWriteAttributes
from backstop_mcp.features.org_people_writes.commands.modify_contact_location_command import (
    ModifyContactLocationCommand,
)
from backstop_mcp.features.org_people_writes.responses import UpdatedOrganizationResponse
from backstop_mcp.features.org_people_writes.update_organization_input import (
    UpdateOrganizationInput,
)
from backstop_mcp.features.system_users import SystemUsersService

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

_Document = BackstopApiSingleResourceDocument[OrganizationWriteAttributes]
_RESOURCE_TYPE = "organizations"


class UpdateOrganizationCommand:
    """Update one organization via `PATCH /organizations/{id}`, then apply location writes."""

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
        self, *, new_organization_fields: UpdateOrganizationInput, party_id: str
    ) -> UpdatedOrganizationResponse:
        with _tracer.start_as_current_span("org_people_writes.command.update_organization") as span:
            span.set_attribute("party_id", party_id)
            owner = await self._system_users_service.resolve_relationship(
                new_organization_fields.owner_login
            )
            await self._patch(new_organization_fields, party_id=party_id, owner=owner)
            location_id = await self._modify_contact_location_command.run(
                party_id=party_id,
                location=new_organization_fields.location,
                delete_location_id=new_organization_fields.delete_location_id,
            )
            logger.info(
                "org_people_writes.organization.updated",
                extra={"id": party_id, "location_id": location_id},
            )
            return UpdatedOrganizationResponse(
                id=party_id,
                resource_type=_RESOURCE_TYPE,
                location_id=location_id,
            )

    async def _patch(
        self,
        new_organization_fields: UpdateOrganizationInput,
        *,
        party_id: str,
        owner: dict[str, object] | None,
    ) -> None:
        attributes = omit_none_values(
            {
                "name": new_organization_fields.name,
                "legalName": new_organization_fields.legal_name,
                "aliases": new_organization_fields.aliases,
                "contactDescription": new_organization_fields.contact_description,
                "dateFounded": isoformat(new_organization_fields.date_founded),
                "email": new_organization_fields.email,
                "email2": new_organization_fields.email2,
                "email3": new_organization_fields.email3,
                "website": new_organization_fields.website,
                "otherId": new_organization_fields.other_id,
                "investableAssets": new_organization_fields.investable_assets,
                "numberOfEmployees": new_organization_fields.number_of_employees,
                "internalOrganization": new_organization_fields.internal_organization,
                "ria": new_organization_fields.ria,
                "matchingDomains": (
                    list(new_organization_fields.matching_domains)
                    if new_organization_fields.matching_domains is not None
                    else None
                ),
            }
        )
        relationships = omit_none_values(
            {
                "contactSource": relationship_to_one(
                    "contact-sources", new_organization_fields.contact_source_id
                ),
                "referralSource": relationship_to_one(
                    "contacts", new_organization_fields.referral_source_id
                ),
                "representative": owner,
                "primaryContact": relationship_to_one(
                    "people", new_organization_fields.primary_contact_id
                ),
                "categories": relationship_data(
                    "contact-categories", new_organization_fields.add_category_ids
                ),
            }
        )
        # A to-many PATCH appends; `data: []` is the only clear. The replacement ids
        # cannot go on this first PATCH — they would be added to the existing list.
        # Clear here, then a second PATCH appends the new members when the list is
        # non-empty.
        if new_organization_fields.replace_category_ids is not None:
            relationships["categories"] = relationship_data("contact-categories", ())
        if not attributes and not relationships:
            return
        path = f"/{_RESOURCE_TYPE}/{quote(party_id, safe='')}"
        await self._client.patch(
            path,
            schema=_Document,
            json=json_api_update(
                resource_type=_RESOURCE_TYPE,
                resource_id=party_id,
                attributes=attributes,
                relationships=relationships or None,
            ),
        )
        # Replacement members cannot go on the first PATCH: a to-many write
        # appends, so they would sit on top of the uncleared list. This request
        # runs only after `data: []` has cleared `categories`.
        if new_organization_fields.replace_category_ids:
            await self._client.patch(
                path,
                schema=_Document,
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
