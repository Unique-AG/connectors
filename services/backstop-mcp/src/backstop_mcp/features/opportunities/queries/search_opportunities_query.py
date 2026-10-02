"""Firm-wide `GET /opportunities` walk: sparse fields and includes, filtered in memory.

`filter[representative.name][eq]` is the only server-side filter that works, and it matches the
representative stored on the deal — often blank. A colleague's pipeline is the representative on
the investor organization, so this walk does not send that filter. It side-loads
`investor.representative` and keeps deals by that login. `filter[stage.name]`,
`filter[product.name]`, and `filter[isOpen]` are `400 Invalid filter field` too, so every filter
is client-side. The investor include arrives as a `contacts` resource, so the sparse key is
`fields[contacts]`, not `fields[organizations]`. That key must list `representative`, or the
organization's representative linkage is dropped from the side-load
(`docs/json/opportunities_include_investor_representative.json`).
"""

import asyncio
import logging
from collections.abc import Sequence
from typing import Literal

from pydantic import ValidationError

from backstop_mcp.backstop_client import BackstopClient, Included, IncludedResource
from backstop_mcp.features.collection_scan import (
    AggregateBucketResponse,
    scan_coverage,
)
from backstop_mcp.features.custom_fields import (
    CustomFieldFilters,
    CustomFieldMatch,
    CustomFieldsService,
    normalize_matches,
    satisfies_every,
    stored_custom_field_values,
)
from backstop_mcp.features.opportunities.api_responses import (
    OpportunityResource,
    SearchContactAttributes,
    SearchProductAttributes,
)
from backstop_mcp.features.opportunities.resource_utils import (
    MapOpportunityToResponseUtil,
    aggregate_search_opportunities,
)
from backstop_mcp.features.opportunities.responses import (
    InvestorFromOpportunityResponse,
    ProductFromOpportunityResponse,
    SearchOpportunitiesResolvedResponse,
    SearchOpportunityRowResponse,
)
from backstop_mcp.features.system_users import SystemUserAttributes
from backstop_mcp.features.ui_links import BuildEntityLinkUtil, OpportunityLinkTarget

logger = logging.getLogger(__name__)


# Scan ceiling. `GET /opportunities` has no wall of its own, and `parallel=True` builds one
# coroutine per page from `meta.totalResourceCount` and accumulates every row — so an unbounded
# walk is bounded only by the tenant. `scan_coverage` reports when this ceiling is hit.
MAX_OPPORTUNITY_SCAN_RECORDS = 20_000

type SearchMode = Literal["rows", "aggregate"]
type OpportunityGroupBy = Literal["stage", "product", "period", "party"]


class SearchOpportunitiesQuery:
    """Walk `GET /opportunities` and project onto sparse search rows or aggregates."""

    def __init__(
        self,
        *,
        client: BackstopClient,
        map_opportunity_to_response_util: MapOpportunityToResponseUtil,
        custom_fields_service: CustomFieldsService,
        build_entity_link_util: BuildEntityLinkUtil,
    ) -> None:
        self._client: BackstopClient = client
        self.map_opportunity_to_response_util: MapOpportunityToResponseUtil = (
            map_opportunity_to_response_util
        )
        self._custom_fields_service: CustomFieldsService = custom_fields_service
        self._build_entity_link_util: BuildEntityLinkUtil = build_entity_link_util

    async def run(
        self,
        *,
        representative: str | None = None,
        is_open: bool | None = None,
        stage: str | None = None,
        products: Sequence[str] = (),
        custom_fields: Sequence[CustomFieldMatch] = (),
        exclude_custom_fields: bool = False,
        mode: SearchMode = "rows",
        group_by: OpportunityGroupBy | None = None,
        fields: frozenset[str],
    ) -> SearchOpportunitiesResolvedResponse:
        """Walk the firm-wide opportunities collection, then filter and project.

        The catalog load runs in parallel with the walk: mapping each row through
        `join_values` would otherwise wait for a cold catalog after the last page, and a
        miss must be reported as `custom_fields_unavailable` rather than inferred from
        empty values.
        """
        predicates = normalize_matches(custom_fields)
        pages, catalog = await asyncio.gather(
            self._client.paginate(
                "/opportunities",
                schema=OpportunityResource,
                params=self._query_params(exclude_custom_fields=exclude_custom_fields),
                max_records=MAX_OPPORTUNITY_SCAN_RECORDS,
                page_size=500,
                parallel=True,
            ),
            self._custom_fields_service.load_catalog(),
        )
        # Indexed once for the whole walk. This loop follows two relationships per opportunity
        # against one array holding every side-loaded investor, product and stage from every page.
        included = Included(pages.included)
        opportunities_mapped: list[SearchOpportunityRowResponse] = []
        dropped = 0
        for opportunity in pages.items:
            if not satisfies_every(opportunity.attributes.regular_custom_field_values, predicates):
                continue
            try:
                opportunity_mapped = await self.map_opportunity_to_response_util.run(
                    row=opportunity,
                    api_include_resources=pages.included,
                    custom_fields_filters=CustomFieldFilters(),
                    include_stage_history=False,
                    url=self._build_entity_link_util.canonical_url(
                        target=OpportunityLinkTarget(entity_id=opportunity.id),
                    ),
                )
                investor_include = included.first(
                    opportunity,
                    "investor",
                    schema=IncludedResource[SearchContactAttributes],
                )
                investor = InvestorFromOpportunityResponse.from_included(investor_include)
                investor_representative = (
                    None
                    if investor_include is None
                    else self._login(
                        included.first(
                            investor_include,
                            "representative",
                            schema=IncludedResource[SystemUserAttributes],
                        )
                    )
                )
                product_response = ProductFromOpportunityResponse.from_included(
                    included.first(
                        opportunity,
                        "product",
                        schema=IncludedResource[SearchProductAttributes],
                    )
                )
                opportunities_mapped.append(
                    SearchOpportunityRowResponse.from_opportunity(
                        opportunity_mapped,
                        investor=investor,
                        product=product_response,
                        investor_representative=investor_representative,
                        representative=self._login(
                            included.first(
                                opportunity,
                                "representative",
                                schema=IncludedResource[SystemUserAttributes],
                            )
                        ),
                        custom_field_values=stored_custom_field_values(
                            opportunity.attributes.regular_custom_field_values
                        )
                        or None,
                    )
                )
            except ValidationError as exc:
                dropped += 1
                logger.warning(
                    "opportunities.search.record.unreadable",
                    extra={"opportunity_id": opportunity.id},
                    exc_info=exc,
                )

        product_needles = tuple(item.strip().casefold() for item in products if item.strip())
        investor_representative = (representative or "").strip().casefold() or None
        selected = tuple(
            opportunity
            for opportunity in opportunities_mapped
            if self._matches_filters(
                opportunity,
                is_open=is_open,
                stage=stage,
                product_needles=product_needles,
                investor_representative=investor_representative,
            )
        )
        projected = fields
        if investor_representative:
            projected = projected | {"investor_representative"}
        if not exclude_custom_fields:
            projected = projected | {"custom_field_values"}
        return self._to_response(
            selected,
            mode=mode,
            fields=projected,
            group_by=group_by,
            opportunities_received=len(pages.items),
            opportunities_dropped=dropped,
            total_count=pages.total_count,
            truncated=pages.truncated,
            custom_fields_unavailable=catalog is None,
        )

    def _query_params(self, *, exclude_custom_fields: bool) -> dict[str, object]:
        wire_fields = [
            "name",
            "isOpen",
            "probability",
            "requestedAmount",
            "allocatedAmount",
            "weightedValue",
            "weightedAllocatedValue",
            "currencyCode",
            "expectedInvestmentDate",
            "closedDate",
            "daysOpen",
            "daysInCurrentStage",
            "dateEnteredCurrentStage",
            "previousStage",
            "representative",
        ]
        if not exclude_custom_fields:
            wire_fields.append("regularCustomFieldValues")
        return {
            "include": "investor,investor.representative,representative,product,stage",
            "fields[contacts]": "name,country,state,city,specificResource,representative",
            "fields[system-users]": "userName",
            "fields[products]": "name,configuration",
            "fields[opportunity-stages]": "name",
            "fields[opportunities]": ",".join(wire_fields),
        }

    def _login(self, user: IncludedResource[SystemUserAttributes] | None) -> str | None:
        if user is None or user.attributes.user_name is None:
            return None
        return user.attributes.user_name.strip() or None

    def _matches_filters(
        self,
        opportunity: SearchOpportunityRowResponse,
        *,
        is_open: bool | None,
        stage: str | None,
        product_needles: Sequence[str],
        investor_representative: str | None,
    ) -> bool:
        if is_open is not None and opportunity.is_open is not is_open:
            return False
        if (
            investor_representative is not None
            and (opportunity.investor_representative or "").casefold() != investor_representative
        ):
            return False
        if stage is not None:
            name = (opportunity.stage or "").casefold()
            if name != stage.strip().casefold():
                return False
        return not product_needles or self._matches_product(opportunity.product, product_needles)

    def _matches_product(
        self, product: ProductFromOpportunityResponse | None, needles: Sequence[str]
    ) -> bool:
        """Short name exact, or display name substring. Several needles are OR.

        `needles` arrive already stripped and casefolded.
        """
        if product is None:
            return False
        short = (product.short_name or "").casefold()
        name = (product.name or "").casefold()
        return any(short == needle or needle in name for needle in needles)

    def _to_response(
        self,
        selected: Sequence[SearchOpportunityRowResponse],
        *,
        mode: SearchMode,
        fields: frozenset[str],
        group_by: OpportunityGroupBy | None,
        opportunities_received: int,
        opportunities_dropped: int,
        total_count: int | None,
        truncated: bool,
        custom_fields_unavailable: bool,
    ) -> SearchOpportunitiesResolvedResponse:
        coverage = scan_coverage(
            rows_scanned=opportunities_received,
            visible_count=total_count,
            rows_dropped=opportunities_dropped,
            ceiling=MAX_OPPORTUNITY_SCAN_RECORDS,
            ceiling_clamped=truncated,
            # One `paginate` call: a failed page raises rather than returning a short list, so this
            # walk has no partial mode to report.
            partial_due_to_error=False,
        )
        opportunities: tuple[SearchOpportunityRowResponse, ...] = ()
        aggregates: tuple[AggregateBucketResponse, ...] = ()
        if mode == "rows":
            opportunities = tuple(opportunity.project(fields=fields) for opportunity in selected)
        else:
            assert group_by is not None
            aggregates = tuple(
                AggregateBucketResponse.from_dto(bucket)
                for bucket in aggregate_search_opportunities(selected, group_by=group_by)
            )
        return SearchOpportunitiesResolvedResponse(
            mode=mode,
            coverage=coverage,
            rows=opportunities,
            aggregates=aggregates,
            custom_fields_unavailable=custom_fields_unavailable,
        )
