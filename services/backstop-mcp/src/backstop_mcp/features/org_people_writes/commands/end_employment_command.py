"""PATCH `/entity-relationships/{id}` with `endDate` only."""

import logging
from datetime import date
from urllib.parse import quote

from fastmcp.exceptions import ToolError
from opentelemetry import trace

from backstop_mcp.backstop_client import (
    BackstopApiResource,
    BackstopApiSingleResourceDocument,
    BackstopClient,
    Included,
    isoformat,
    json_api_update,
)
from backstop_mcp.features.data_hygiene import (
    EmploymentIndexFactory,
    EntityRelationshipAttributes,
    EntityRelationshipRef,
    RelationshipTypeAttributes,
)
from backstop_mcp.features.org_people_writes.responses import EndedEmploymentResponse

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

_Document = BackstopApiSingleResourceDocument[EntityRelationshipAttributes]
_Relationship = BackstopApiResource[EntityRelationshipAttributes]
_TypeResource = BackstopApiResource[RelationshipTypeAttributes]
_RESOURCE_TYPE = "entity-relationships"
_NOT_YET_FORMER = (
    "The end date is recorded but the person still reads as a current contact until "
    + "that date has passed."
)


class EndEmploymentCommand:
    """Find the person↔organization employment row and write `endDate` once."""

    def __init__(
        self,
        *,
        client: BackstopClient,
        employment_index_factory: EmploymentIndexFactory,
    ) -> None:
        self._client: BackstopClient = client
        self._employment_index_factory: EmploymentIndexFactory = employment_index_factory

    async def run(
        self,
        *,
        person_id: str,
        person_search_type: str,
        organization_id: str,
        end_date: date,
    ) -> EndedEmploymentResponse:
        with _tracer.start_as_current_span("org_people_writes.command.end_employment") as span:
            span.set_attribute("person_id", person_id)
            span.set_attribute("organization_id", organization_id)
            relationship_id = await self._open_employment_id(
                person_id=person_id,
                person_search_type=person_search_type,
                organization_id=organization_id,
            )
            path = f"/{_RESOURCE_TYPE}/{quote(relationship_id, safe='')}"
            await self._client.patch(
                path,
                schema=_Document,
                json=json_api_update(
                    resource_type=_RESOURCE_TYPE,
                    resource_id=relationship_id,
                    attributes={"endDate": isoformat(end_date)},
                ),
            )
            reread = await self._client.get(path, schema=_Document)
            stored_end_date = reread.data.attributes.end_date
            warnings: tuple[str, ...] = ()
            if stored_end_date != end_date:
                warnings += (
                    f"Backstop stored an end date of {stored_end_date or 'nothing'} rather "
                    + f"than the requested {isoformat(end_date)}. The employment was not "
                    + "ended as asked.",
                )
            elif not end_date < self._employment_index_factory.today():
                warnings += (_NOT_YET_FORMER,)
            logger.info(
                "org_people_writes.employment.ended",
                extra={
                    "id": relationship_id,
                    "person_id": person_id,
                    "organization_id": organization_id,
                },
            )
            return EndedEmploymentResponse(
                id=relationship_id,
                resource_type=_RESOURCE_TYPE,
                end_date=stored_end_date,
                warnings=warnings,
            )

    async def _open_employment_id(
        self,
        *,
        person_id: str,
        person_search_type: str,
        organization_id: str,
    ) -> str:
        page = await self._client.paginate(
            f"/{person_search_type}/{quote(person_id, safe='')}/entityRelationships",
            schema=_Relationship,
            params={"include": EntityRelationshipRef.TYPE.value},
            max_records=None,
            page_size=100,
        )
        types = Included(page.included).by_type(
            EntityRelationshipRef.TYPES_RESOURCE.value, schema=_TypeResource
        )
        open_ids = [
            resource.id
            for resource in page.items
            if self._is_open_employment(
                resource, organization_id=organization_id, relationship_types=types
            )
        ]
        if not open_ids:
            raise ToolError(
                "No current employment relationship links person "
                + f"{person_id} to organization {organization_id}."
            )
        if len(open_ids) > 1:
            raise ToolError(
                "Multiple current employment relationships link person "
                + f"{person_id} to organization {organization_id}: "
                + ", ".join(open_ids)
                + ". Say which one to end."
            )
        return open_ids[0]

    def _is_open_employment(
        self,
        resource: _Relationship,
        *,
        organization_id: str,
        relationship_types: list[_TypeResource],
    ) -> bool:
        destination = resource.attributes.destination_entity
        if destination is None or destination.resource_id != organization_id:
            return False
        index = self._employment_index_factory.index(
            relationships=[resource],
            relationship_types=relationship_types,
        )
        return any(link.status == "current" for link in index.links())
