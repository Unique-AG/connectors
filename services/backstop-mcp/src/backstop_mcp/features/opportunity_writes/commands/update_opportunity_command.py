"""PATCH `/opportunities/{id}`. The only write that moves a deal's stage."""

import logging
from datetime import date
from urllib.parse import quote

from fastmcp.exceptions import ToolError
from opentelemetry import trace

from backstop_mcp.backstop_client import (
    BackstopApiSingleResourceDocument,
    BackstopClient,
    Included,
    IncludedResource,
    json_api_update,
    omit_none_values,
    relationship_data,
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
    opportunity_entity_type_id,
    opportunity_relationships,
)
from backstop_mcp.features.opportunity_writes.responses import UpdatedOpportunityResponse
from backstop_mcp.features.opportunity_writes.update_opportunity_input import UpdateOpportunityInput
from backstop_mcp.features.system_users import SystemUsersService
from backstop_mcp.utils import first_item, identifiable_value

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

_Document = BackstopApiSingleResourceDocument[OpportunityResourceAttributes]
_RESOURCE_TYPE = "opportunities"


class UpdateOpportunityCommand:
    """Update one opportunity via `PATCH /opportunities/{id}`, then re-read the stage."""

    def __init__(
        self,
        *,
        client: BackstopClient,
        opportunity_stages_service: OpportunityStagesService,
        system_users_service: SystemUsersService,
    ) -> None:
        self._client: BackstopClient = client
        self._opportunity_stages_service: OpportunityStagesService = opportunity_stages_service
        self._system_users_service: SystemUsersService = system_users_service

    async def run(self, *, new_opportunity: UpdateOpportunityInput) -> UpdatedOpportunityResponse:
        with _tracer.start_as_current_span("opportunity_writes.command.update") as span:
            span.set_attribute("opportunity_id", new_opportunity.opportunity_id)
            current = await self._read(new_opportunity.opportunity_id)
            catalog = await self._opportunity_stages_service.get_catalog()
            requested_stage = (
                await self._opportunity_stages_service.find_by_stage_name(
                    name=new_opportunity.stage,
                    entity_type_id=opportunity_entity_type_id(current),
                )
                if new_opportunity.stage is not None
                else None
            )
            self._raise_if_backdated(
                requested=new_opportunity.stage_effective_date,
                date_entered_current_stage=current.data.attributes.date_entered_current_stage,
            )
            owner = await self._system_users_service.resolve_relationship(
                new_opportunity.owner_login
            )
            add_notify, add_skipped = await self._resolve_logins(
                new_opportunity.add_users_to_notify
            )
            replace_notify, replace_skipped = await self._resolve_logins(
                new_opportunity.replace_users_to_notify
            )
            await self._patch(
                new_opportunity,
                requested_stage=requested_stage,
                owner=owner,
                add_notify=add_notify,
                replace_notify=replace_notify,
            )
            written = await self._read(new_opportunity.opportunity_id)
            stage_name, stage_id = self._stage_from_document(written, catalog)
            warnings = self._stage_warnings(
                requested=requested_stage, landed_name=stage_name, landed_id=stage_id
            ) + self._skipped_login_warnings((*add_skipped, *replace_skipped))
            logger.info(
                "opportunity_writes.opportunity.updated",
                extra={
                    "id": new_opportunity.opportunity_id,
                    "stage": stage_name,
                    "warnings": len(warnings),
                },
            )
            return UpdatedOpportunityResponse(
                id=new_opportunity.opportunity_id,
                resource_type=_RESOURCE_TYPE,
                stage=stage_name,
                stage_id=stage_id,
                warnings=warnings,
            )

    async def _read(self, opportunity_id: str) -> _Document:
        path = f"/{_RESOURCE_TYPE}/{quote(opportunity_id, safe='')}"
        return await self._client.get(
            path, schema=_Document, params={"include": OPPORTUNITY_READ_INCLUDE}
        )

    async def _patch(
        self,
        opportunity: UpdateOpportunityInput,
        *,
        requested_stage: OpportunityStageResponse | None,
        owner: dict[str, object] | None,
        add_notify: tuple[str, ...] | None,
        replace_notify: tuple[str, ...] | None,
    ) -> None:
        path = f"/{_RESOURCE_TYPE}/{quote(opportunity.opportunity_id, safe='')}"
        attributes = omit_none_values(opportunity_attributes(opportunity))
        relationships = omit_none_values(
            opportunity_relationships(
                opportunity,
                owner=owner,
                stage_id=requested_stage.id if requested_stage else None,
                add_notify=add_notify,
                omit_empty=False,
            )
        )
        # A to-many PATCH appends; `data: []` is the only clear. Replacing the notify
        # list is therefore this PATCH (clear, plus any other fields) and, when the
        # replacement is non-empty, a second PATCH that appends the new members.
        if replace_notify is not None:
            relationships["ccedUsers"] = relationship_data("system-users", ())

        if not attributes and not relationships:
            return

        await self._client.patch(
            path,
            schema=_Document,
            json=json_api_update(
                resource_type=_RESOURCE_TYPE,
                resource_id=opportunity.opportunity_id,
                attributes=attributes,
                relationships=relationships or None,
            ),
        )

        if replace_notify:
            await self._client.patch(
                path,
                schema=_Document,
                json=json_api_update(
                    resource_type=_RESOURCE_TYPE,
                    resource_id=opportunity.opportunity_id,
                    attributes={},
                    relationships={"ccedUsers": relationship_data("system-users", replace_notify)},
                ),
            )

    def _raise_if_backdated(
        self, *, requested: date | None, date_entered_current_stage: date | None
    ) -> None:
        if requested is None or date_entered_current_stage is None:
            return
        if requested < date_entered_current_stage:
            raise ToolError(
                "stage_effective_date is earlier than the deal's dateEnteredCurrentStage. "
                + "Backstop would record a history row without moving the deal. Omit the date "
                + "to move it today."
            )

    async def _resolve_logins(
        self, logins: tuple[str, ...] | None
    ) -> tuple[tuple[str, ...] | None, tuple[str, ...]]:
        if logins is None:
            return None, ()
        if not logins:
            return (), ()
        ids: list[str] = []
        skipped: list[str] = []
        for login in logins:
            user = await self._system_users_service.find_by_user_name(login)
            if user is None:
                logger.warning(
                    "opportunity_writes.login.unresolved",
                    extra={"login": identifiable_value(login)},
                )
                skipped.append(login)
                continue
            logger.info(
                "opportunity_writes.login.resolved",
                extra={"login": identifiable_value(login), "id": user.id},
            )
            ids.append(user.id)
        if not ids:
            return None, tuple(skipped)
        return tuple(ids), tuple(skipped)

    def _skipped_login_warnings(self, skipped: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(
            f"Skipped notify login {login!r}: no system user with that login. "
            + "Use list_system_users."
            for login in skipped
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
