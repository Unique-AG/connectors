"""One person record by collection and id, with employment links, includes, custom fields."""

import asyncio
from collections.abc import Sequence
from urllib.parse import quote

from backstop_mcp.backstop_client import BackstopApiResourceDocument, BackstopClient
from backstop_mcp.features.custom_fields import CustomFieldFilters, CustomFieldsService
from backstop_mcp.features.data_hygiene import (
    EmploymentIndexFactory,
    EntityRelationshipInclude,
    project_entity_relationships,
)
from backstop_mcp.features.includes import PersonInclude, PersonIncludesResponse, include_plan
from backstop_mcp.features.org_people.api_responses import PersonAttributes
from backstop_mcp.features.org_people.responses import PartyPersonResponse, PersonRecordResponse


class GetPersonQuery:
    """GET one person, project its employment links, and join its custom-field values."""

    def __init__(
        self,
        *,
        client: BackstopClient,
        employment_index_factory: EmploymentIndexFactory,
        custom_fields_service: CustomFieldsService,
    ) -> None:
        self._client: BackstopClient = client
        self._employment_index_factory: EmploymentIndexFactory = employment_index_factory
        self._custom_fields_service: CustomFieldsService = custom_fields_service

    async def run(
        self,
        *,
        search_type: str,
        party_id: str,
        include: Sequence[PersonInclude] = (),
        custom_fields_filters: CustomFieldFilters,
    ) -> PartyPersonResponse:
        """The person's record, employment links, requested side-loads, and custom fields.

        The catalog load runs in parallel with the person GET: `join_values` would otherwise
        wait for a cold catalog after the record has already arrived.
        """
        # Quick-search for people uses the shared PERSON_* types, so a hit may be a
        # contact/employee; follow `party.search_type` instead of hard-coding `/people`.
        person_path = f"/{search_type}/{quote(party_id, safe='')}"
        person_includes_plan = include_plan(PersonIncludesResponse, requested=include)
        # Employment include is always on; the caller's include list is empty when unused.
        include_param = ",".join(
            part
            for part in (EntityRelationshipInclude.for_employment(), person_includes_plan.param)
            if part
        )
        person_document, _ = await asyncio.gather(
            self._client.get(
                person_path,
                params={"include": include_param} if include_param else None,
                schema=BackstopApiResourceDocument[PersonAttributes],
            ),
            self._custom_fields_service.load_catalog(),
        )
        person_attributes = person_document.require_data(path=person_path).attributes
        entity_relationships = project_entity_relationships(person_document)
        employment_index = self._employment_index_factory.index(
            relationships=entity_relationships.relationships,
            relationship_types=entity_relationships.relationship_types,
        )
        custom_field_values = await self._custom_fields_service.join_values(
            person_attributes.regular_custom_field_values,
            filters=custom_fields_filters,
        )
        return PartyPersonResponse(
            person=PersonRecordResponse.from_attributes(person_attributes),
            employments=employment_index.links(),
            included=(
                person_includes_plan.project(document=person_document)
                if person_includes_plan.planned
                else None
            ),
            custom_field_values=custom_field_values,
        )
