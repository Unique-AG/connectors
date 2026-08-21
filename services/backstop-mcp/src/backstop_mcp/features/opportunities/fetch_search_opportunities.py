"""Firm-wide `GET /opportunities` walk: sparse fields, includes, optional login filter.

`filter[representative.name][eq]` is the only server-side filter that works, and it takes a
**login** (`userName` from `list_system_users`), not a display name. `filter[stage.name]`,
`filter[product.name]`, and `filter[isOpen]` are `400 Invalid filter field` — those stay
client-side after this walk. The investor include arrives as a `contacts` resource, so the
sparse key is `fields[contacts]`, not `fields[organizations]`.
"""

import asyncio
import logging
from collections.abc import Awaitable, Mapping, Sequence

from pydantic import ValidationError

from backstop_mcp.backstop_client import (
    BackstopApiResource,
    BackstopClient,
    IncludedIndex,
    IncludedResource,
    follow_indexed,
    included_resource,
    index_included,
)
from backstop_mcp.features.opportunities.api_responses import (
    SearchContactAttributes,
    SearchProductAttributes,
)
from backstop_mcp.features.opportunities.fetch_opportunities import (
    OpportunityResource,
    await_vocabulary,
    current_stage_id,
    resolve_stage_name,
    stage_names_from_included,
)
from backstop_mcp.features.opportunities.internal_dto import (
    InvestorChipDto,
    OpportunityStageDto,
    ProductChipDto,
    SearchOpportunitiesFetchDto,
    SearchOpportunityDto,
)
from backstop_mcp.features.opportunities.responses import OpportunityResponse

logger = logging.getLogger(__name__)

_PATH = "/opportunities"
_PAGE_SIZE = 500

# Scan ceiling. `GET /opportunities` has no wall of its own, and `parallel=True` builds one
# coroutine per page from `meta.totalResourceCount` and accumulates every row — so an unbounded
# walk is bounded only by the tenant. 1,206 rows measured here, so this is ~16x headroom on this
# instance and a stated limit on one 50x larger, reported through `scan_coverage`.
MAX_OPPORTUNITY_SCAN_RECORDS = 20_000
_INCLUDE = "investor,product,stage"
_CONTACT_FIELDS = "name,country,state,city"
_PRODUCT_FIELDS = "name"
_STAGE_FIELDS = "name"
_OPPORTUNITY_FIELDS = (
    "name,isOpen,probability,requestedAmount,allocatedAmount,weightedValue,"
    "weightedAllocatedValue,currencyCode,"
    "expectedInvestmentDate,closedDate,daysOpen,daysInCurrentStage,dateEnteredCurrentStage,"
    "previousStage"
)

__all__ = ["MAX_OPPORTUNITY_SCAN_RECORDS", "fetch_search_opportunities"]


def _chip_from_index[T](
    index: IncludedIndex,
    resource: OpportunityResource,
    relationship: str,
    *,
    schema: type[IncludedResource[T]],
) -> IncludedResource[T] | None:
    matches = follow_indexed(index, resource, relationship)
    if not matches:
        return None
    return included_resource(matches[0], schema=schema)


def _investor(index: IncludedIndex, resource: OpportunityResource) -> InvestorChipDto | None:
    chip = _chip_from_index(
        index, resource, "investor", schema=IncludedResource[SearchContactAttributes]
    )
    if chip is None:
        return None
    return InvestorChipDto(
        id=chip.id,
        name=chip.attributes.name,
        country=chip.attributes.country,
        state=chip.attributes.state,
        city=chip.attributes.city,
    )


def _product(index: IncludedIndex, resource: OpportunityResource) -> ProductChipDto | None:
    chip = _chip_from_index(
        index, resource, "product", schema=IncludedResource[SearchProductAttributes]
    )
    if chip is None:
        return None
    return ProductChipDto(id=chip.id, name=chip.attributes.name)


def _from_deal(
    deal: OpportunityResponse,
    *,
    investor: InvestorChipDto | None,
    product: ProductChipDto | None,
) -> SearchOpportunityDto:
    return SearchOpportunityDto(
        id=deal.id,
        name=deal.name,
        stage=deal.stage,
        stage_id=deal.stage_id,
        previous_stage=deal.previous_stage,
        is_open=deal.is_open,
        probability=deal.probability,
        requested_amount=deal.requested_amount,
        allocated_amount=deal.allocated_amount,
        weighted_value=deal.weighted_value,
        weighted_allocated_value=deal.weighted_allocated_value,
        currency=deal.currency,
        expected_investment_date=deal.expected_investment_date,
        closed_date=deal.closed_date,
        days_open=deal.days_open,
        days_in_current_stage=deal.days_in_current_stage,
        date_entered_current_stage=deal.date_entered_current_stage,
        investor=investor,
        product=product,
    )


def _project(
    items: Sequence[OpportunityResource],
    *,
    included: Sequence[dict[str, object]],
    vocabulary: Mapping[str, OpportunityStageDto],
) -> tuple[tuple[SearchOpportunityDto, ...], int]:
    side_loaded = stage_names_from_included(included)
    # Indexed once for the whole walk. `follow_included` indexes on every call, and this loop
    # follows two relationships per row against one array holding every side-loaded investor,
    # product and stage from every page — 1,206 rows would rebuild that map 2,412 times.
    index = index_included(included)
    projected: list[SearchOpportunityDto] = []
    dropped = 0
    for resource in items:
        stage_id = current_stage_id(resource)
        try:
            deal = OpportunityResponse.from_resource(
                resource,
                stage=resolve_stage_name(stage_id, side_loaded=side_loaded, vocabulary=vocabulary),
                stage_id=stage_id,
                stage_history=(),
            )
        except ValidationError as exc:
            dropped += 1
            logger.warning(
                "opportunities.search.record.unreadable",
                extra={"opportunity_id": resource.id},
                exc_info=exc,
            )
            continue
        projected.append(
            _from_deal(
                deal,
                investor=_investor(index, resource),
                product=_product(index, resource),
            )
        )
    return tuple(projected), dropped


def _params(*, representative: str | None) -> dict[str, object]:
    params: dict[str, object] = {
        "include": _INCLUDE,
        "fields[contacts]": _CONTACT_FIELDS,
        "fields[products]": _PRODUCT_FIELDS,
        "fields[opportunity-stages]": _STAGE_FIELDS,
        "fields[opportunities]": _OPPORTUNITY_FIELDS,
    }
    if representative:
        params["filter[representative.name][eq]"] = representative
    return params


async def fetch_search_opportunities(
    client: BackstopClient,
    *,
    representative: str | None = None,
    vocabulary: Mapping[str, OpportunityStageDto] | Awaitable[Mapping[str, OpportunityStageDto]],
) -> SearchOpportunitiesFetchDto:
    """Walk the firm-wide opportunities collection, optionally filtered by login."""
    page, vocabulary_rows = await asyncio.gather(
        client.paginate(
            _PATH,
            schema=BackstopApiResource[dict[str, object]],
            params=_params(representative=representative),
            max_records=MAX_OPPORTUNITY_SCAN_RECORDS,
            page_size=_PAGE_SIZE,
            parallel=True,
        ),
        await_vocabulary(vocabulary),
    )
    rows, dropped = _project(page.items, included=page.included, vocabulary=vocabulary_rows)
    return SearchOpportunitiesFetchDto(
        rows=rows,
        rows_received=len(page.items),
        rows_dropped=dropped,
        total_count=page.total_count,
        truncated=page.truncated,
    )
