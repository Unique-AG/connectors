"""Firm-wide `GET /opportunities` search. `representative` is the one server-side filter
(`filter[representative.name][eq]`, the deal's own representative, exact login); the stage,
product and open filters are `400` server-side, so they run in memory on each page read.

Rows mode returns one page of matches per call and a cursor at the next unread record.
Aggregate mode walks the whole collection and has no cursor.
"""

import asyncio
import logging
import math
from collections.abc import Callable, Mapping, Sequence
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from backstop_mcp.backstop_client import BackstopClient, Included, IncludedResource, SinglePage
from backstop_mcp.features.collection_scan import (
    AggregateBucketResponse,
    collect_page,
    continuation,
    scan_coverage,
)
from backstop_mcp.features.custom_fields import (
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
    get_stage_id_to_name_map,
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


_PAGE_SIZE = 500
# Pages read at once when an in-memory filter can leave a Backstop page short of a result page.
_FILTERED_CONCURRENCY = 5

type SearchMode = Literal["rows", "aggregate"]
type OpportunityGroupBy = Literal["stage", "product", "period", "party"]


class _ScannedOpportunity(BaseModel):
    """One record of a Backstop page after mapping: its row, or why it has none."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    # Record offset in the server-ordered collection.
    position: int
    # `None` when a custom-field predicate rejected the record or it could not be read.
    row: SearchOpportunityRowResponse | None = None
    unreadable: bool = False


class SearchOpportunitiesQuery:
    """Read `GET /opportunities` and project onto sparse search rows or aggregates."""

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
        result_size: int,
        start_offset: int = 0,
        fingerprint: str,
    ) -> SearchOpportunitiesResolvedResponse:
        """Read the firm-wide opportunities collection, then filter and project.

        Rows mode reads from `start_offset` until `result_size` rows match; aggregate mode
        ignores the paging arguments and reads every page. The catalog load runs in parallel
        with the read: a miss must be reported as `custom_fields_unavailable` rather than
        inferred from empty values. Rows publish the stored custom-field text, so they are not
        joined against the catalog.
        """
        predicates = normalize_matches(custom_fields)
        product_needles = tuple(item.strip().casefold() for item in products if item.strip())

        def keep(row: SearchOpportunityRowResponse) -> bool:
            return self._matches_filters(
                row, is_open=is_open, stage=stage, product_needles=product_needles
            )

        params = self._query_params(
            representative=representative, exclude_custom_fields=exclude_custom_fields
        )
        if mode == "aggregate":
            assert group_by is not None
            return await self._aggregate(
                params=params, predicates=predicates, keep=keep, group_by=group_by
            )
        in_memory_filter = any(
            (predicates, product_needles, is_open is not None, stage is not None)
        )
        return await self._fetch_page(
            params=params,
            predicates=predicates,
            keep=keep,
            fields=fields if exclude_custom_fields else fields | {"custom_field_values"},
            result_size=result_size,
            start_offset=start_offset,
            fingerprint=fingerprint,
            concurrency=_FILTERED_CONCURRENCY if in_memory_filter else 1,
        )

    async def _fetch_page(
        self,
        *,
        params: dict[str, object],
        predicates: Sequence[CustomFieldMatch],
        keep: Callable[[SearchOpportunityRowResponse], bool],
        fields: frozenset[str],
        result_size: int,
        start_offset: int,
        fingerprint: str,
        concurrency: int,
    ) -> SearchOpportunitiesResolvedResponse:
        # `sort=id` pins the order so a cursor offset lands on the same record next call;
        # Backstop's default order is not documented as stable.
        sorted_params = {**params, "sort": "id"}

        async def read_at(offset: int) -> SinglePage[_ScannedOpportunity]:
            page = await self._client.fetch_page(
                "/opportunities",
                schema=OpportunityResource,
                params=sorted_params,
                page_size=_PAGE_SIZE,
                offset=offset,
            )
            return SinglePage[_ScannedOpportunity](
                items=await self._scan(
                    page.items,
                    included=page.included,
                    predicates=predicates,
                    first_position=offset,
                ),
                total_count=page.total_count,
            )

        unreadable_positions: list[int] = []

        def select(
            page: SinglePage[_ScannedOpportunity],
        ) -> list[tuple[int, SearchOpportunityRowResponse]]:
            unreadable_positions.extend(item.position for item in page.items if item.unreadable)
            return [
                (index, item.row)
                for index, item in enumerate(page.items)
                if item.row is not None and keep(item.row)
            ]

        collected, catalog = await asyncio.gather(
            collect_page(
                read_at=read_at,
                select=select,
                start_offset=start_offset,
                output_page_size=result_size,
                api_page_size=_PAGE_SIZE,
                concurrency=concurrency,
            ),
            self._custom_fields_service.load_catalog(),
        )
        # Only records this call consumed: not the head of a re-read page before the cursor,
        # nor the tail after the row that filled the page.
        consumed_end = math.inf if collected.next_offset is None else collected.next_offset
        dropped = sum(
            1 for position in unreadable_positions if start_offset <= position < consumed_end
        )
        logger.info(
            "opportunities.search.page",
            extra={
                "stop_reason": collected.stop_reason,
                "records_scanned": collected.records_scanned,
                "request_count": collected.request_count,
                "rows": len(collected.rows),
            },
        )
        return SearchOpportunitiesResolvedResponse(
            mode="rows",
            coverage=scan_coverage(
                rows_scanned=collected.records_scanned,
                visible_count=collected.total_count,
                rows_dropped=dropped,
                ceiling=None,
                ceiling_clamped=False,
                partial_due_to_error=False,
            ),
            rows=tuple(row.project(fields=fields) for row in collected.rows),
            custom_fields_unavailable=catalog is None,
            continuation=continuation(
                stop_reason=collected.stop_reason,
                next_offsets=() if collected.next_offset is None else (collected.next_offset,),
                fingerprint=fingerprint,
                rows_returned=len(collected.rows),
            ),
        )

    async def _aggregate(
        self,
        *,
        params: dict[str, object],
        predicates: Sequence[CustomFieldMatch],
        keep: Callable[[SearchOpportunityRowResponse], bool],
        group_by: OpportunityGroupBy,
    ) -> SearchOpportunitiesResolvedResponse:
        pages, catalog = await asyncio.gather(
            self._client.paginate(
                "/opportunities",
                schema=OpportunityResource,
                params=params,
                max_records=None,
                page_size=_PAGE_SIZE,
                parallel=True,
            ),
            self._custom_fields_service.load_catalog(),
        )
        # Indexed once for the whole walk, against one array holding every side-loaded
        # investor, product and stage from every page.
        scanned = await self._scan(pages.items, included=pages.included, predicates=predicates)
        selected = tuple(item.row for item in scanned if item.row is not None and keep(item.row))
        return SearchOpportunitiesResolvedResponse(
            mode="aggregate",
            coverage=scan_coverage(
                rows_scanned=len(pages.items),
                visible_count=pages.total_count,
                rows_dropped=sum(1 for item in scanned if item.unreadable),
                ceiling=None,
                ceiling_clamped=False,
                # One `paginate` call: a failed page raises rather than returning a short list,
                # so this walk has no partial mode to report.
                partial_due_to_error=False,
            ),
            aggregates=tuple(
                AggregateBucketResponse.from_dto(bucket)
                for bucket in aggregate_search_opportunities(selected, group_by=group_by)
            ),
            custom_fields_unavailable=catalog is None,
        )

    async def _scan(
        self,
        records: Sequence[OpportunityResource],
        *,
        included: Sequence[dict[str, object]],
        predicates: Sequence[CustomFieldMatch],
        first_position: int = 0,
    ) -> list[_ScannedOpportunity]:
        """Map every record against the `included` array sent with it.

        Each mapped record follows two relationships into `included`, so it and the stage
        names are indexed once per call rather than per record.
        """
        index = Included(included)
        stage_id_to_name = get_stage_id_to_name_map(included)
        return [
            await self._scan_one(
                opportunity,
                position=position,
                included=included,
                index=index,
                stage_id_to_name=stage_id_to_name,
                predicates=predicates,
            )
            for position, opportunity in enumerate(records, start=first_position)
        ]

    async def _scan_one(
        self,
        opportunity: OpportunityResource,
        *,
        position: int,
        included: Sequence[dict[str, object]],
        index: Included,
        stage_id_to_name: Mapping[str, str],
        predicates: Sequence[CustomFieldMatch],
    ) -> _ScannedOpportunity:
        if not satisfies_every(opportunity.attributes.regular_custom_field_values, predicates):
            return _ScannedOpportunity(position=position)
        try:
            opportunity_mapped = await self.map_opportunity_to_response_util.run(
                row=opportunity,
                api_include_resources=included,
                custom_fields_filters=None,
                include_stage_history=False,
                stage_id_to_name=stage_id_to_name,
                url=self._build_entity_link_util.canonical_url(
                    target=OpportunityLinkTarget(entity_id=opportunity.id),
                ),
            )
            investor_include = index.first(
                opportunity,
                "investor",
                schema=IncludedResource[SearchContactAttributes],
            )
            investor_representative = (
                None
                if investor_include is None
                else self._login(
                    index.first(
                        investor_include,
                        "representative",
                        schema=IncludedResource[SystemUserAttributes],
                    )
                )
            )
            row = SearchOpportunityRowResponse.from_opportunity(
                opportunity_mapped,
                investor=InvestorFromOpportunityResponse.from_included(investor_include),
                product=ProductFromOpportunityResponse.from_included(
                    index.first(
                        opportunity,
                        "product",
                        schema=IncludedResource[SearchProductAttributes],
                    )
                ),
                investor_representative=investor_representative,
                representative=self._login(
                    index.first(
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
        except ValidationError as exc:
            logger.warning(
                "opportunities.search.record.unreadable",
                extra={"opportunity_id": opportunity.id},
                exc_info=exc,
            )
            return _ScannedOpportunity(position=position, unreadable=True)
        return _ScannedOpportunity(position=position, row=row)

    def _query_params(
        self, *, representative: str | None, exclude_custom_fields: bool
    ) -> dict[str, object]:
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
        params: dict[str, object] = {
            # `investor.representative` feeds the `investor_representative` row field only.
            "include": "investor,investor.representative,representative,product,stage",
            "fields[contacts]": "name,country,state,city,specificResource,representative",
            "fields[system-users]": "userName",
            "fields[products]": "name,configuration",
            "fields[opportunity-stages]": "name",
            "fields[opportunities]": ",".join(wire_fields),
        }
        login = (representative or "").strip()
        if login:
            # Exact and case-sensitive on the login; a display name matches nothing.
            params["filter[representative.name][eq]"] = login
        return params

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
    ) -> bool:
        if is_open is not None and opportunity.is_open is not is_open:
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
