"""POST `/entity-relationships`, then re-read the created employment."""

import logging
from datetime import date
from urllib.parse import quote

from mcp_observability import traced

from backstop_mcp.backstop_client import (
    BackstopApiSingleResourceDocument,
    BackstopClient,
    isoformat,
    json_api_create,
    omit_none_values,
    relationship_to_one,
    resource_pointer,
)
from backstop_mcp.features.data_hygiene import (
    EntityRelationshipAttributes,
    EntityRelationshipRef,
)
from backstop_mcp.features.org_people_writes.entity_relationship_types_service import (
    EntityRelationshipTypesService,
)
from backstop_mcp.features.org_people_writes.responses import CreatedEmploymentResponse

logger = logging.getLogger(__name__)

_Document = BackstopApiSingleResourceDocument[EntityRelationshipAttributes]
_RESOURCE_TYPE = "entity-relationships"
_ORGANIZATION_TYPE = "organizations"


class CreateEmploymentCommand:
    """Create one person↔organization employment via `POST /entity-relationships`."""

    def __init__(
        self,
        *,
        client: BackstopClient,
        entity_relationship_types_service: EntityRelationshipTypesService,
    ) -> None:
        self._client: BackstopClient = client
        self._entity_relationship_types_service: EntityRelationshipTypesService = (
            entity_relationship_types_service
        )

    @traced(
        arguments=("person_id", "person_search_type", "organization_id", "start_date"),
        result=lambda created: {"id": created.id},
    )
    async def run(
        self,
        *,
        person_id: str,
        person_search_type: str,
        organization_id: str,
        start_date: date,
    ) -> CreatedEmploymentResponse:
        employment_type = await self._entity_relationship_types_service.get_employment_type()
        created = await self._client.post(
            f"/{_RESOURCE_TYPE}",
            schema=_Document,
            json=json_api_create(
                resource_type=_RESOURCE_TYPE,
                attributes=omit_none_values(
                    {
                        "sourceEntity": resource_pointer(
                            resource_id=person_id,
                            resource_type=person_search_type,
                        ),
                        "destinationEntity": resource_pointer(
                            resource_id=organization_id,
                            resource_type=_ORGANIZATION_TYPE,
                        ),
                        "startDate": isoformat(start_date),
                    }
                ),
                relationships=omit_none_values(
                    {
                        "entityRelationshipType": relationship_to_one(
                            EntityRelationshipRef.TYPES_RESOURCE, employment_type.id
                        ),
                    }
                ),
            ),
        )
        created_id = created.data.id
        written = await self._client.get(
            f"/{_RESOURCE_TYPE}/{quote(created_id, safe='')}", schema=_Document
        )
        logger.info(
            "Created employment",
            extra={
                "id": created_id,
                "person_id": person_id,
                "organization_id": organization_id,
            },
        )
        return CreatedEmploymentResponse(
            id=created_id,
            resource_type=_RESOURCE_TYPE,
            start_date=written.data.attributes.start_date,
        )
