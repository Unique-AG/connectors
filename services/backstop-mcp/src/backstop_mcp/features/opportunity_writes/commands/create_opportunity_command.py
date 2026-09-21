"""POST `/opportunities`, then re-read the created deal with stage and entity type."""

import logging
from urllib.parse import quote

from opentelemetry import trace

from backstop_mcp.backstop_client import (
    BackstopApiSingleResourceDocument,
    BackstopClient,
    Included,
    IncludedResource,
    json_api_create,
    omit_none_values,
)
from backstop_mcp.features.opportunities import (
    OpportunityResourceAttributes,
    OpportunityStageAttributes,
    OpportunityStageResponse,
    OpportunityStagesService,
)
from backstop_mcp.features.opportunity_writes.commands._opportunity_attributes import (
    OPPORTUNITY_READ_INCLUDE,
    opportunity_attributes,
    opportunity_relationships,
    unique_catalog_entity_type_id,
)
from backstop_mcp.features.opportunity_writes.create_opportunity_input import (
    CreateOpportunityInput,
)
from backstop_mcp.features.opportunity_writes.responses import CreatedOpportunityResponse
from backstop_mcp.features.system_users import SystemUsersService
from backstop_mcp.features.ui_links import BuildEntityLinkUtil, OpportunityLinkTarget
from backstop_mcp.utils import first_item

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

_Document = BackstopApiSingleResourceDocument[OpportunityResourceAttributes]
_RESOURCE_TYPE = "opportunities"


class CreateOpportunityCommand:
    """Create one opportunity via `POST /opportunities`, then report the re-read stage."""

    def __init__(
        self,
        *,
        client: BackstopClient,
        opportunity_stages_service: OpportunityStagesService,
        system_users_service: SystemUsersService,
        build_entity_link_util: BuildEntityLinkUtil,
    ) -> None:
        self._client: BackstopClient = client
        self._opportunity_stages_service: OpportunityStagesService = opportunity_stages_service
        self._system_users_service: SystemUsersService = system_users_service
        self._build_entity_link_util: BuildEntityLinkUtil = build_entity_link_util

    async def run(
        self, *, opportunity: CreateOpportunityInput, investor_id: str
    ) -> CreatedOpportunityResponse:
        with _tracer.start_as_current_span("opportunity_writes.command.create") as span:
            span.set_attribute("investor_id", investor_id)
            requested_stage = None
            if opportunity.stage is not None:
                catalog = await self._opportunity_stages_service.get_catalog()
                requested_stage = await self._opportunity_stages_service.find_by_stage_name(
                    name=opportunity.stage,
                    entity_type_id=unique_catalog_entity_type_id(catalog),
                )
            owner = await self._system_users_service.resolve_relationship(opportunity.owner_login)
            attributes = omit_none_values(opportunity_attributes(opportunity))
            relationships = omit_none_values(
                opportunity_relationships(
                    opportunity,
                    owner=owner,
                    stage_id=requested_stage.id if requested_stage else None,
                    add_notify=None,
                    omit_empty=True,
                    investor_id=investor_id,
                )
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
                f"/{_RESOURCE_TYPE}/{quote(created_id, safe='')}",
                schema=_Document,
                params={"include": OPPORTUNITY_READ_INCLUDE},
            )
            catalog = await self._opportunity_stages_service.get_catalog()
            stage_name, stage_id = self._stage_from_document(written, catalog)
            warnings = self._stage_warnings(
                requested=requested_stage, landed_name=stage_name, landed_id=stage_id
            )
            logger.info(
                "opportunity_writes.opportunity.created",
                extra={
                    "id": created_id,
                    "stage": stage_name,
                    "warnings": len(warnings),
                },
            )
            return CreatedOpportunityResponse(
                id=created_id,
                resource_type=_RESOURCE_TYPE,
                name=written.data.attributes.name,
                stage=stage_name,
                stage_id=stage_id,
                warnings=warnings,
                url=self._build_entity_link_util.canonical_url(
                    target=OpportunityLinkTarget(entity_id=created_id),
                ),
            )

    def _stage_from_document(
        self,
        document: _Document,
        catalog: dict[str, OpportunityStageResponse],
    ) -> tuple[str | None, str | None]:
        stage_id = first_item(document.data.related_ids("stage"))
        if stage_id is None:
            return None, None
        known = catalog.get(stage_id)
        if known is not None:
            return known.name, known.id
        includes = Included(document.included)
        chip = includes.first(
            document.data, "stage", schema=IncludedResource[OpportunityStageAttributes]
        )
        name = chip.attributes.name if chip is not None else None
        return name, stage_id

    def _stage_warnings(
        self,
        *,
        requested: OpportunityStageResponse | None,
        landed_name: str | None,
        landed_id: str | None,
    ) -> tuple[str, ...]:
        if requested is None:
            return ()
        if landed_id == requested.id or (
            landed_name is not None and landed_name.casefold() == requested.name.casefold()
        ):
            return ()
        landed = landed_name or landed_id or "its previous stage"
        return (
            f"The requested stage {requested.name!r} was not applied; "
            + f"the deal is still in {landed}.",
        )
