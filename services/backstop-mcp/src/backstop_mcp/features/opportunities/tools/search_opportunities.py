"""`search_opportunities`: firm-wide pipeline walk over `GET /opportunities`.

`filter[representative.name][eq]` is the only working server-side filter and takes a **login**
from `list_system_users`, not a display name. Stage, product, and open/closed are client-side.
"""

import logging
from datetime import date
from typing import Annotated, Literal, Self

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client_for_current_caller
from backstop_mcp.features.collection_scan import (
    AggregateBucketResponse,
    ScanCoverageResponse,
    project_fields,
    scan_coverage,
)
from backstop_mcp.features.opportunities import (
    MAX_OPPORTUNITY_SCAN_RECORDS,
    OpportunityGroupBy,
    OpportunityStagesService,
    SearchOpportunitiesFetchDto,
    SearchOpportunityDto,
    aggregate_search_opportunities,
    fetch_search_opportunities,
    get_opportunity_stages_service_factory,
)
from backstop_mcp.models import OmitNoneModel, published_output_schema

logger = logging.getLogger(__name__)

_DEFAULT_MAX_ROWS = 100
_MAX_ROWS = 1_000

SearchMode = Literal["rows", "aggregate"]
SearchRowField = Literal[
    "id",
    "name",
    "stage",
    "stage_id",
    "previous_stage",
    "is_open",
    "probability",
    "requested_amount",
    "allocated_amount",
    "weighted_value",
    "weighted_allocated_value",
    "currency",
    "expected_investment_date",
    "closed_date",
    "days_open",
    "days_in_current_stage",
    "date_entered_current_stage",
    "investor",
    "product",
]
_DEFAULT_FIELDS: frozenset[str] = frozenset(
    {"id", "name", "stage", "is_open", "expected_investment_date", "investor", "product"}
)


class InvestorChipResponse(OmitNoneModel):
    """The investor on a deal. The include arrives as a `contacts` resource."""

    id: str = Field(description="Backstop contacts id of the investor. Echo it; never invent one.")
    name: str | None = Field(default=None, description="Investor name as published on the contact.")
    country: str | None = Field(default=None, description="Country on the investor contact.")
    state: str | None = Field(
        default=None, description="State or province on the investor contact."
    )
    city: str | None = Field(default=None, description="City on the investor contact.")


class ProductChipResponse(OmitNoneModel):
    """The product this deal is for."""

    id: str = Field(
        description="Backstop product id. Echo it into get_time_series / get_product_investors."
    )
    name: str | None = Field(default=None, description="Product name as published.")


class SearchOpportunityRowResponse(OmitNoneModel):
    """One deal from the firm-wide pipeline walk. Only requested `fields` are populated."""

    id: str | None = Field(
        default=None,
        description=(
            "Backstop id of the opportunity. Always populated, even when omitted from `fields`."
        ),
    )
    name: str | None = Field(default=None, description="Deal name, usually 'investor - fund'.")
    stage: str | None = Field(default=None, description="The stage the deal is in now.")
    stage_id: str | None = Field(default=None, description="Backstop id of the current stage.")
    previous_stage: str | None = Field(
        default=None, description="The stage the deal most recently LEFT — not where it is now."
    )
    is_open: bool | None = Field(default=None, description="Whether the deal is still open.")
    probability: float | None = Field(
        default=None, description="Likelihood of closing as a fraction: 0.3 is 30%."
    )
    requested_amount: float | None = Field(default=None, description="Amount asked, in `currency`.")
    allocated_amount: float | None = Field(
        default=None, description="Amount allocated so far, in `currency`."
    )
    weighted_value: float | None = Field(
        default=None,
        description="Backstop's requested amount times probability — use for book-wide ranking.",
    )
    weighted_allocated_value: float | None = Field(
        default=None, description="Backstop's allocated amount times probability."
    )
    currency: str | None = Field(default=None, description="ISO currency of both amounts.")
    expected_investment_date: date | None = Field(
        default=None, description="Day the investment is expected."
    )
    closed_date: date | None = Field(default=None, description="Day the deal closed, if it has.")
    days_open: int | None = Field(default=None, description="Days the deal has been open.")
    days_in_current_stage: int | None = Field(
        default=None, description="Days the deal has sat in `stage`."
    )
    date_entered_current_stage: date | None = Field(
        default=None, description="Day the deal entered `stage`."
    )
    investor: InvestorChipResponse | None = Field(
        default=None, description="Investor contact chip when the include arrived."
    )
    product: ProductChipResponse | None = Field(
        default=None, description="Product chip when the include arrived."
    )

    @classmethod
    def from_dto(cls, row: SearchOpportunityDto, *, fields: frozenset[str]) -> Self:
        return project_fields(row, fields=fields, into=cls)


class SearchOpportunitiesResolvedResponse(OmitNoneModel):
    """A completed firm-wide pipeline search: row bodies or aggregate counts, plus coverage."""

    status: Literal["resolved"] = Field(
        default="resolved",
        description="Always 'resolved': the walk ran. An empty `rows` list is 'none matching'.",
    )
    mode: Literal["rows", "aggregate"] = Field(
        description="`rows` returns deal bodies; `aggregate` returns counts grouped by `group_by`."
    )
    coverage: ScanCoverageResponse = Field(
        description="How much of the matching set was scanned, and whether it was truncated."
    )
    rows: tuple[SearchOpportunityRowResponse, ...] = Field(
        default=(),
        description=(
            "Matching deals after client-side filters. Empty in aggregate mode. `id` is always "
            "present so the row can be handed to get_opportunities_by_ids. Amounts are already "
            "on this walk — select them with `fields`. Master Pipeline custom fields and stage "
            "history are not; fetch those ids with get_opportunities_by_ids."
        ),
    )
    aggregates: tuple[AggregateBucketResponse, ...] = Field(
        default=(),
        description="Count buckets in aggregate mode. Empty in rows mode.",
    )


def _matches(
    row: SearchOpportunityDto,
    *,
    is_open: bool | None,
    stage: str | None,
    product: str | None,
) -> bool:
    if is_open is not None and row.is_open is not is_open:
        return False
    if stage is not None:
        name = (row.stage or "").casefold()
        if name != stage.strip().casefold():
            return False
    if product is not None:
        name = (row.product.name if row.product is not None else "") or ""
        if name.casefold() != product.strip().casefold():
            return False
    return True


def _resolved(
    fetch: SearchOpportunitiesFetchDto,
    *,
    matching: tuple[SearchOpportunityDto, ...],
    mode: SearchMode,
    fields: frozenset[str],
    max_rows: int,
    group_by: OpportunityGroupBy | None,
) -> SearchOpportunitiesResolvedResponse:
    truncated_by_row_cap = mode == "rows" and len(matching) > max_rows
    visible = fetch.total_count
    coverage = scan_coverage(
        rows_scanned=fetch.rows_received,
        visible_count=visible,
        rows_dropped=fetch.rows_dropped,
        ceiling=MAX_OPPORTUNITY_SCAN_RECORDS,
        ceiling_clamped=fetch.truncated,
        truncated_by_row_cap=truncated_by_row_cap,
        # One `paginate` call: a failed page raises rather than returning a short list, so this
        # walk has no partial mode to report.
        partial_due_to_error=False,
    )
    rows: tuple[SearchOpportunityRowResponse, ...] = ()
    aggregates: tuple[AggregateBucketResponse, ...] = ()
    if mode == "rows":
        rows = tuple(
            SearchOpportunityRowResponse.from_dto(row, fields=fields) for row in matching[:max_rows]
        )
    else:
        assert group_by is not None
        aggregates = tuple(
            AggregateBucketResponse.from_dto(bucket)
            for bucket in aggregate_search_opportunities(matching, group_by=group_by)
        )
    return SearchOpportunitiesResolvedResponse(
        mode=mode,
        coverage=coverage,
        rows=rows,
        aggregates=aggregates,
    )


@tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    output_schema=published_output_schema(SearchOpportunitiesResolvedResponse),
)
async def search_opportunities(
    representative: Annotated[
        str | None,
        Field(
            description=(
                "Backstop **login** (`user_name` from list_system_users), not a display name. "
                "This is the only server-side filter. 'Ben Lazarus' returns 0 rows; "
                "'blazarus' returns that colleague's book. A disabled login returns empty — "
                "check list_system_users before concluding there is no pipeline."
            )
        ),
    ] = None,
    is_open: Annotated[
        bool | None,
        Field(
            description=("Client-side open/closed split. filter[isOpen] is 400 on this collection.")
        ),
    ] = None,
    stage: Annotated[
        str | None,
        Field(
            description=(
                "Client-side stage name match. filter[stage.name] is 400 on this collection."
            )
        ),
    ] = None,
    product: Annotated[
        str | None,
        Field(
            description=(
                "Client-side product name match. filter[product.name] is 400 on this collection."
            )
        ),
    ] = None,
    mode: Annotated[
        SearchMode,
        Field(description="`rows` (default) or `aggregate` for counts without row bodies."),
    ] = "rows",
    group_by: Annotated[
        OpportunityGroupBy | None,
        Field(description="Required when mode is aggregate: stage, product, period, or party."),
    ] = None,
    max_rows: Annotated[
        int,
        Field(
            ge=1,
            le=_MAX_ROWS,
            description=(
                f"Row-body cap in rows mode. Does not limit the walk, which reads up to "
                f"{MAX_OPPORTUNITY_SCAN_RECORDS} rows and says so in `coverage`, or the "
                "aggregate counts."
            ),
        ),
    ] = _DEFAULT_MAX_ROWS,
    fields: Annotated[
        list[SearchRowField] | None,
        Field(
            description=(
                "Sparse row fields. Defaults to id, name, stage, is_open, dates, chips. "
                "`id` is always included."
            ),
        ),
    ] = None,
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    opportunity_stages_service: OpportunityStagesService = Depends(
        get_opportunity_stages_service_factory
    ),
) -> SearchOpportunitiesResolvedResponse:
    """Walk the firm-wide pipeline.

    Use for coverage questions, stuck-in-stage, closing windows, and product pipeline. Pass
    `representative` as a **login** from list_system_users — a display name silently returns
    zero rows. Stage, product, and open/closed are filtered here after the walk;
    filter[stage.name], filter[product.name], and filter[isOpen] are invalid on this collection.

    This walk does not return custom fields or stage history. For those, call
    get_opportunities_by_ids with the ids — `id` is always projected so that handoff works.
    Amounts are on this walk; select them with `fields`.

    For one party's deals, call get_opportunities instead — that is one cheap sub-collection,
    not this walk. `mode=aggregate` with `group_by` answers a counting question without row
    bodies. Investor geography is on the `investor` chip (the include is a contacts resource).
    """
    if mode == "aggregate" and group_by is None:
        raise ValueError("group_by is required when mode is aggregate")
    if mode == "rows" and group_by is not None:
        raise ValueError("group_by is only used when mode is aggregate")

    logger.info(
        "opportunities.search.start",
        extra={"representative": representative, "mode": mode, "stage": stage, "product": product},
    )
    fetch = await fetch_search_opportunities(
        client, representative=representative, opportunity_stages_service=opportunity_stages_service
    )
    matching = tuple(
        row for row in fetch.rows if _matches(row, is_open=is_open, stage=stage, product=product)
    )
    selected_fields = (frozenset(fields) if fields else _DEFAULT_FIELDS) | {"id"}
    return _resolved(
        fetch,
        matching=matching,
        mode=mode,
        fields=selected_fields,
        max_rows=max_rows,
        group_by=group_by,
    )
