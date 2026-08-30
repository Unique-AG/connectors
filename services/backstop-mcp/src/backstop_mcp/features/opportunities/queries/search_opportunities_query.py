"""Firm-wide `GET /opportunities` walk: sparse fields, includes, optional login filter.

`filter[representative.name][eq]` is the only server-side filter that works, and it takes a
**login** (`userName` from `list_system_users`), not a display name. `filter[stage.name]`,
`filter[product.name]`, and `filter[isOpen]` are `400 Invalid filter field` — those stay
client-side after this walk. The investor include arrives as a `contacts` resource, so the
sparse key is `fields[contacts]`, not `fields[organizations]`.
"""

import asyncio
import logging
from collections.abc import Sequence
from typing import Literal

from pydantic import ValidationError

from backstop_mcp.backstop_client import (
    BackstopClient,
    IncludedResource,
    first_included,
    index_included,
)
from backstop_mcp.features.collection_scan import (
    AggregateBucketResponse,
    scan_coverage,
)
from backstop_mcp.features.custom_fields import CustomFieldFilters, CustomFieldsService
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

logger = logging.getLogger(__name__)

# Scan ceiling. `GET /opportunities` has no wall of its own, and `parallel=True` builds one
# coroutine per page from `meta.totalResourceCount` and accumulates every row — so an unbounded
# walk is bounded only by the tenant. 1,206 rows measured here, so this is ~16x headroom on this
# instance and a stated limit on one 50x larger, reported through `scan_coverage`.
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
    ) -> None:
        self._client: BackstopClient = client
        self.map_opportunity_to_response_util: MapOpportunityToResponseUtil = (
            map_opportunity_to_response_util
        )
        self._custom_fields_service: CustomFieldsService = custom_fields_service

    async def run(
        self,
        *,
        representative: str | None = None,
        is_open: bool | None = None,
        stage: str | None = None,
        product: str | None = None,
        mode: SearchMode = "rows",
        group_by: OpportunityGroupBy | None = None,
        max_rows: int,
        fields: frozenset[str],
    ) -> SearchOpportunitiesResolvedResponse:
        """Walk the firm-wide opportunities collection, then filter and project.

        The catalog load runs in parallel with the walk: mapping each row through
        `join_values` would otherwise wait for a cold catalog after the last page, and a
        miss must be reported as `custom_fields_unavailable` rather than inferred from
        empty values.
        """
        pages, catalog = await asyncio.gather(
            self._client.paginate(
                "/opportunities",
                schema=OpportunityResource,
                params=self._query_params(representative=representative),
                max_records=MAX_OPPORTUNITY_SCAN_RECORDS,
                page_size=500,
                parallel=True,
            ),
            self._custom_fields_service.load_catalog(self._client),
        )
        # Indexed once for the whole walk. `follow_included` indexes on every call, and this loop
        # follows two relationships per opportunity against one array holding every side-loaded
        # investor, product and stage from every page — 1,206 rows would rebuild that map 2,412
        # times.
        included_index = index_included(pages.included)
        opportunities_mapped: list[SearchOpportunityRowResponse] = []
        dropped = 0
        for opportunity in pages.items:
            try:
                opportunity_mapped = await self.map_opportunity_to_response_util.run(
                    row=opportunity,
                    api_include_resources=pages.included,
                    custom_fields_filters=CustomFieldFilters(),
                    include_stage_history=False,
                )
                investor = InvestorFromOpportunityResponse.from_included(
                    first_included(
                        included_index,
                        opportunity,
                        "investor",
                        schema=IncludedResource[SearchContactAttributes],
                    )
                )
                product_response = ProductFromOpportunityResponse.from_included(
                    first_included(
                        included_index,
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
                    )
                )
            except ValidationError as exc:
                dropped += 1
                logger.warning(
                    "opportunities.search.record.unreadable",
                    extra={"opportunity_id": opportunity.id},
                    exc_info=exc,
                )

        selected = tuple(
            opportunity
            for opportunity in opportunities_mapped
            if self._matches_filters(opportunity, is_open=is_open, stage=stage, product=product)
        )
        return self._to_response(
            selected,
            mode=mode,
            fields=fields,
            max_rows=max_rows,
            group_by=group_by,
            opportunities_received=len(pages.items),
            opportunities_dropped=dropped,
            total_count=pages.total_count,
            truncated=pages.truncated,
            custom_fields_unavailable=catalog is None,
        )

    def _query_params(self, *, representative: str | None) -> dict[str, object]:
        params: dict[str, object] = {
            "include": "investor,product,stage",
            "fields[contacts]": "name,country,state,city",
            "fields[products]": "name",
            "fields[opportunity-stages]": "name",
            "fields[opportunities]": (
                "name,isOpen,probability,requestedAmount,allocatedAmount,weightedValue,"
                "weightedAllocatedValue,currencyCode,"
                "expectedInvestmentDate,closedDate,daysOpen,daysInCurrentStage,"
                "dateEnteredCurrentStage,previousStage"
            ),
        }
        if representative:
            params["filter[representative.name][eq]"] = representative
        return params

    def _matches_filters(
        self,
        opportunity: SearchOpportunityRowResponse,
        *,
        is_open: bool | None,
        stage: str | None,
        product: str | None,
    ) -> bool:
        if is_open is not None and opportunity.is_open is not is_open:
            return False
        if stage is not None:
            name = (opportunity.stage or "").casefold()
            if name != stage.strip().casefold():
                return False
        if product is not None:
            name = (opportunity.product.name if opportunity.product is not None else "") or ""
            if name.casefold() != product.strip().casefold():
                return False
        return True

    def _to_response(
        self,
        selected: Sequence[SearchOpportunityRowResponse],
        *,
        mode: SearchMode,
        fields: frozenset[str],
        max_rows: int,
        group_by: OpportunityGroupBy | None,
        opportunities_received: int,
        opportunities_dropped: int,
        total_count: int | None,
        truncated: bool,
        custom_fields_unavailable: bool,
    ) -> SearchOpportunitiesResolvedResponse:
        truncated_by_row_cap = mode == "rows" and len(selected) > max_rows
        coverage = scan_coverage(
            rows_scanned=opportunities_received,
            visible_count=total_count,
            rows_dropped=opportunities_dropped,
            ceiling=MAX_OPPORTUNITY_SCAN_RECORDS,
            ceiling_clamped=truncated,
            truncated_by_row_cap=truncated_by_row_cap,
            # One `paginate` call: a failed page raises rather than returning a short list, so this
            # walk has no partial mode to report.
            partial_due_to_error=False,
        )
        opportunities: tuple[SearchOpportunityRowResponse, ...] = ()
        aggregates: tuple[AggregateBucketResponse, ...] = ()
        if mode == "rows":
            opportunities = tuple(
                opportunity.project(fields=fields) for opportunity in selected[:max_rows]
            )
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
