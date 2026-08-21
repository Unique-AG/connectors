"""`search_opportunities`: firm-wide pipeline walk over `GET /opportunities`.

`filter[representative.name][eq]` is the only working server-side filter and takes a **login**
from `list_system_users`, not a display name. Stage, product, and open/closed are client-side.
"""

import logging
from typing import Annotated, Literal, Self

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client
from backstop_mcp.features.collection_scan import (
    AggregateBucketResponse,
    ScanCoverageResponse,
    scan_coverage,
)
from backstop_mcp.features.opportunities import (
    OpportunityGroupBy,
    OpportunityStagesService,
    SearchOpportunitiesFetchDto,
    SearchOpportunityDto,
    aggregate_search_opportunities,
    fetch_search_opportunities,
    get_opportunity_stages_service,
)
from backstop_mcp.models import OmitNoneModel, published_output_schema

logger = logging.getLogger(__name__)

_DEFAULT_MAX_ROWS = 100
_MAX_ROWS = 1_000
# No endpoint wall on GET /opportunities; scan_coverage still needs a ceiling that will not fire.
_NO_CEILING = -1

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

    id: str | None = Field(default=None, description="Backstop id of the opportunity.")
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
    expected_investment_date: object = Field(
        default=None, description="Day the investment is expected."
    )
    closed_date: object = Field(default=None, description="Day the deal closed, if it has.")
    days_open: int | None = Field(default=None, description="Days the deal has been open.")
    days_in_current_stage: int | None = Field(
        default=None, description="Days the deal has sat in `stage`."
    )
    date_entered_current_stage: object = Field(
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
        payload: dict[str, object] = {}
        if "id" in fields:
            payload["id"] = row.id
        if "name" in fields:
            payload["name"] = row.name
        if "stage" in fields:
            payload["stage"] = row.stage
        if "stage_id" in fields:
            payload["stage_id"] = row.stage_id
        if "previous_stage" in fields:
            payload["previous_stage"] = row.previous_stage
        if "is_open" in fields:
            payload["is_open"] = row.is_open
        if "probability" in fields:
            payload["probability"] = row.probability
        if "requested_amount" in fields:
            payload["requested_amount"] = row.requested_amount
        if "allocated_amount" in fields:
            payload["allocated_amount"] = row.allocated_amount
        if "weighted_value" in fields:
            payload["weighted_value"] = row.weighted_value
        if "weighted_allocated_value" in fields:
            payload["weighted_allocated_value"] = row.weighted_allocated_value
        if "currency" in fields:
            payload["currency"] = row.currency
        if "expected_investment_date" in fields:
            payload["expected_investment_date"] = row.expected_investment_date
        if "closed_date" in fields:
            payload["closed_date"] = row.closed_date
        if "days_open" in fields:
            payload["days_open"] = row.days_open
        if "days_in_current_stage" in fields:
            payload["days_in_current_stage"] = row.days_in_current_stage
        if "date_entered_current_stage" in fields:
            payload["date_entered_current_stage"] = row.date_entered_current_stage
        if "investor" in fields and row.investor is not None:
            payload["investor"] = InvestorChipResponse.model_validate(row.investor.model_dump())
        if "product" in fields and row.product is not None:
            payload["product"] = ProductChipResponse.model_validate(row.product.model_dump())
        return cls.model_validate(payload)


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
        description="Matching deals after client-side filters. Empty in aggregate mode.",
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
        ceiling=_NO_CEILING,
        ceiling_clamped=False,
        truncated_by_row_cap=truncated_by_row_cap,
        partial_due_to_error=fetch.partial_due_to_error,
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
            description="Row-body cap in rows mode. Does not limit the walk or aggregate counts.",
        ),
    ] = _DEFAULT_MAX_ROWS,
    fields: Annotated[
        list[SearchRowField] | None,
        Field(description="Sparse row fields. Defaults to id, name, stage, is_open, dates, chips."),
    ] = None,
    client: BackstopClient = Depends(get_backstop_client),
    opportunity_stages: OpportunityStagesService = Depends(get_opportunity_stages_service),
) -> SearchOpportunitiesResolvedResponse:
    """Walk the firm-wide pipeline.

    Use for coverage questions, stuck-in-stage, closing windows, and product pipeline. Pass
    `representative` as a **login** from list_system_users — a display name silently returns
    zero rows. Stage, product, and open/closed are filtered here after the walk;
    filter[stage.name], filter[product.name], and filter[isOpen] are invalid on this collection.

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
        client,
        representative=representative,
        vocabulary=opportunity_stages.get(client),
    )
    matching = tuple(
        row for row in fetch.rows if _matches(row, is_open=is_open, stage=stage, product=product)
    )
    selected_fields = frozenset(fields) if fields else _DEFAULT_FIELDS
    return _resolved(
        fetch,
        matching=matching,
        mode=mode,
        fields=selected_fields,
        max_rows=max_rows,
        group_by=group_by,
    )
