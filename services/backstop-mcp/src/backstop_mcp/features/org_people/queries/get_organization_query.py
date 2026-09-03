"""One organization record by id, with optional side-loaded includes and custom fields."""

import asyncio
from collections.abc import Sequence
from urllib.parse import quote

from backstop_mcp.backstop_client import BackstopApiResourceDocument, BackstopClient
from backstop_mcp.features.custom_fields import CustomFieldFilters, CustomFieldsService
from backstop_mcp.features.includes import (
    OrganizationInclude,
    OrganizationIncludesResponse,
    include_plan,
)
from backstop_mcp.features.org_people.api_responses import OrganizationAttributes
from backstop_mcp.features.org_people.responses import (
    OrganizationRecordResponse,
    PartyOrganizationResponse,
)


class GetOrganizationQuery:
    """GET one organization and join its custom-field values."""

    def __init__(
        self,
        *,
        client: BackstopClient,
        custom_fields_service: CustomFieldsService,
    ) -> None:
        self._client: BackstopClient = client
        self._custom_fields_service: CustomFieldsService = custom_fields_service

    async def run(
        self,
        *,
        party_id: str,
        include: Sequence[OrganizationInclude] = (),
        custom_fields_filters: CustomFieldFilters,
    ) -> PartyOrganizationResponse:
        """The organization's record, requested side-loads, and custom fields.

        The catalog load runs in parallel with the organization GET: `join_values` would
        otherwise wait for a cold catalog after the record has already arrived.
        """
        path = f"/organizations/{quote(party_id, safe='')}"
        plan = include_plan(OrganizationIncludesResponse, requested=include)
        document, _ = await asyncio.gather(
            self._client.get(
                path,
                params={"include": plan.param} if plan.param else None,
                schema=BackstopApiResourceDocument[OrganizationAttributes],
            ),
            self._custom_fields_service.load_catalog(),
        )
        attributes = document.require_data(path=path).attributes
        custom_field_values = await self._custom_fields_service.join_values(
            attributes.regular_custom_field_values,
            filters=custom_fields_filters,
        )
        return PartyOrganizationResponse(
            organization=OrganizationRecordResponse.from_attributes(attributes),
            included=plan.project(document=document) if plan.planned else None,
            custom_field_values=custom_field_values,
        )
