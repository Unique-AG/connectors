"""`search_opportunities`: firm-wide pipeline walk over `GET /opportunities`.

`filter[representative.name][eq]` is the only working server-side filter and takes a **login**
from `list_system_users`, not a display name. Stage, product, and open/closed are client-side.
"""

import logging
from typing import Annotated, Literal

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.features.opportunities import (
    MAX_OPPORTUNITY_SCAN_RECORDS,
    SearchMode,
    SearchOpportunitiesQuery,
    SearchOpportunitiesResolvedResponse,
)
from backstop_mcp.features.opportunities.dependencies import (
    get_search_opportunities_query_factory,
)
from backstop_mcp.models import published_output_schema

logger = logging.getLogger(__name__)

_DEFAULT_MAX_ROWS = 100
_MAX_ROWS = 1_000

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
    search_opportunities_query: SearchOpportunitiesQuery = Depends(
        get_search_opportunities_query_factory
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
    return await search_opportunities_query.run(
        representative=representative,
        is_open=is_open,
        stage=stage,
        product=product,
        mode=mode,
        group_by=group_by,
        max_rows=max_rows,
        fields=(frozenset(fields) if fields else _DEFAULT_FIELDS) | {"id"},
    )
