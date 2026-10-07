"""`search_opportunities`: firm-wide pipeline search over `GET /opportunities`.

`representative` is sent as `filter[representative.name][eq]`, the only server-side filter: the
deal-level representative, matched on the exact login. Every other filter is client-side. Rows
mode returns one page per call and a cursor; aggregate mode reads every match.
"""

import logging
from collections.abc import Sequence
from typing import Annotated, Literal

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from backstop_mcp.config import SearchConfig
from backstop_mcp.dependencies import get_search_config
from backstop_mcp.features.collection_scan import SearchCursor, search_fingerprint
from backstop_mcp.features.custom_fields import CustomFieldMatch
from backstop_mcp.features.opportunities import (
    OpportunityGroupBy,
    SearchMode,
    SearchOpportunitiesQuery,
    SearchOpportunitiesResolvedResponse,
)
from backstop_mcp.features.opportunities.dependencies import (
    get_search_opportunities_query_factory,
)
from backstop_mcp.models import CoercedId, NonEmptyStr, published_output_schema

logger = logging.getLogger(__name__)


SearchRowField = Literal[
    "id",
    "url",
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
    "investor_representative",
    "representative",
    "product",
]
_DEFAULT_FIELDS: frozenset[str] = frozenset(
    {"id", "name", "stage", "is_open", "expected_investment_date", "investor", "product"}
)


class OpportunityCustomFieldFilter(BaseModel):
    """One custom-field predicate. Several predicates AND together."""

    definition_id: CoercedId = Field(
        description=(
            "Custom-field definition id from list_custom_fields for opportunities. "
            "Not the field label: two definitions can share a name."
        )
    )
    values: list[NonEmptyStr] = Field(
        min_length=1,
        description=(
            "Stored values that satisfy this predicate, OR. Each is compared whole and "
            "case-insensitively against the select options list_custom_fields returns — "
            "pass the exact option, not a substring. A list "
            "value matches when any element equals one of these. A missing value does not "
            "match — this filter cannot mean 'the field is empty'."
        ),
    )


def _predicates(
    custom_fields: Sequence[OpportunityCustomFieldFilter] | None,
) -> tuple[CustomFieldMatch, ...]:
    if not custom_fields:
        return ()
    return tuple(
        CustomFieldMatch(definition_id=item.definition_id, values=tuple(item.values))
        for item in custom_fields
    )


@tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(SearchOpportunitiesResolvedResponse),
)
async def search_opportunities(
    representative: Annotated[
        str | None,
        Field(
            description=(
                "Backstop **login** (`user_name` from list_system_users), exactly as listed, "
                "not a display name. Keeps the deals assigned to that colleague: the "
                "deal-level representative (`representative` on each row). Not the investor "
                "organization's representative. A display name such as 'Jane Doe' returns 0 "
                "rows. Sent to Backstop as the server-side filter."
            )
        ),
    ] = None,
    is_open: Annotated[
        bool | None,
        Field(description="Open/closed split, applied after the server-side read."),
    ] = None,
    stage: Annotated[
        str | None,
        Field(
            description=(
                "One stage name, exact match, case-insensitive. Applied after the server-side read."
            )
        ),
    ] = None,
    product: Annotated[
        list[str] | None,
        Field(
            description=(
                "Linked fund: short names (exact, e.g. NWON) or display-name substrings. "
                "Several values are OR, so several vehicles can be one search, e.g. "
                '["NWON", "NWOF"]. Resolve names with search_products '
                "first when unsure. Applied after the server-side read."
            )
        ),
    ] = None,
    custom_fields: Annotated[
        list[OpportunityCustomFieldFilter] | None,
        Field(
            description=(
                "Opportunity custom-field predicates, AND. Each is a definition id from "
                "list_custom_fields(entity_types=['opportunities']) plus the exact stored "
                "option (`<option from list_custom_fields>`), not a deal name and not the "
                "linked-fund `product` argument. Applied after the server-side read."
            )
        ),
    ] = None,
    exclude_custom_fields: Annotated[
        bool,
        Field(
            description=(
                "Every row's custom fields come back as `custom_field_values` by default "
                "(the fields a table is grouped or labelled by), so the rows answer the table. "
                "Leave this "
                "false. Set it true only to retry a call that timed out, to see whether "
                "reading the custom fields is what made it slow. Refused together with "
                "`custom_fields`, which needs them."
            )
        ),
    ] = False,
    mode: Annotated[
        SearchMode,
        Field(
            description=(
                "`rows` (default): one page of deals per call, with `continuation` when more "
                "may match. `aggregate`: counts over every match in one call, no cursor."
            )
        ),
    ] = "rows",
    group_by: Annotated[
        OpportunityGroupBy | None,
        Field(
            description=(
                "Required when mode is aggregate: `stage`, `product`, `period`, or `party`. "
                "`period` is YYYY-MM of `expected_investment_date`, else "
                "`date_entered_current_stage`. `party` is the investor. Missing stage is "
                "`(unknown)`; a deal with no product or investor is `(unattributed)`; a "
                "period with no date is `(undated)`."
            )
        ),
    ] = None,
    fields: Annotated[
        list[SearchRowField] | None,
        Field(
            description=(
                "Sparse row fields. Defaults to id, name, stage, is_open, "
                "expected_investment_date, investor, product. "
                "`id` is always included. Select `url` when the answer will link to the "
                "deals — it is off by default so a page stays small."
            ),
        ),
    ] = None,
    cursor: Annotated[
        str | None,
        Field(
            description=(
                "`continuation.cursor` from the previous page of this same search. Repeat "
                "every other argument unchanged; a cursor from different arguments is "
                "rejected. Rows mode only."
            )
        ),
    ] = None,
    search_opportunities_query: SearchOpportunitiesQuery = Depends(
        get_search_opportunities_query_factory
    ),
    search_config: SearchConfig = Depends(get_search_config),
) -> SearchOpportunitiesResolvedResponse:
    """Search the firm-wide pipeline.

    Rows mode returns one page of deals per call. `continuation` means more may match: follow
    `continuation.cursor`, with every other argument unchanged, only when the user needs more
    rows. A counting question uses `mode=aggregate`, which reads every match in one call and
    has no cursor.

    `product` matches the linked fund. A short name matches exactly; a display-name
    substring matches every vehicle whose name contains it. Several `product` values are
    OR. `mode="aggregate", group_by="product"` counts that linked fund. The chip may be
    empty, and then every open deal is `(unattributed)`.

    If a call times out, retry once with `exclude_custom_fields=true` to see whether
    reading them is the cause; otherwise leave it false.
    Do not call get_opportunities_by_ids to re-read fields this search already returned.

    `is_open` means the deal is still in the pipeline. `representative` matches the
    deal-level representative login (`representative` on each row) — the deals assigned to
    that colleague. Pass that **login** from list_system_users. A display name silently
    returns zero rows. Backstop applies `representative`; every other filter is applied
    after the server-side read.
    `coverage.visible_count` is Backstop's total after `representative` and before the
    other filters. An empty `rows` list with no `continuation` means nothing matched.

    A stage-change question ("what moved stage since X") stays on this tool. Select
    `previous_stage` and `date_entered_current_stage` and keep rows whose
    `date_entered_current_stage` is inside the window, including deals that closed — do not
    pass `is_open`. Do not ask the user for those field names, and do not walk
    get_opportunities_by_ids for this question. Those two fields are the latest move per
    deal only; say so. `id` is always projected. `custom_fields_unavailable` means the
    catalog missed: stored values on this row are still the text Backstop sent, and
    get_opportunities_by_ids would not resolve types. Amounts are on these rows; select
    them with `fields`.

    For one party's deals, call get_opportunities instead — that is one cheap sub-collection,
    not this search. This tool has no `party_id`. Investor geography is on the `investor`
    chip (the include is a contacts resource).

    For deals with no activity in 30/60/90 days, pass each distinct `investor.id` and
    `investor.search_type` to get_last_activity_for_parties and bucket by its
    `days_since_last_activity`. Days in stage is not activity.

    A colleague's name (as in "<name>'s pipeline" or "deals assigned to <name>") is resolved
    with list_system_users, never search_people. `investor_representative` is a separate
    output field — the colleague who covers the investor organization. It can differ from
    the deal-level representative and is never filtered on; select it only to compare.

    Call like: {"representative": "jdoe", "is_open": true}
    Compare with the investor organization's coverage: {"representative": "jdoe",
    "is_open": true, "fields": ["name", "stage", "requested_amount", "investor",
    "representative", "investor_representative"]}
    One custom-field option: {"is_open": true, "custom_fields": [{"definition_id":
    "<id from list_custom_fields>", "values": ["<option from list_custom_fields>"]}],
    "fields": ["name", "stage", "requested_amount", "expected_investment_date", "investor"]}
    Several vehicles: {"product": ["NWON", "NWOF"], "is_open": true}
    Stage changes: {"fields": ["name", "stage", "previous_stage",
    "date_entered_current_stage", "is_open", "investor"]}
    """
    if mode == "aggregate" and group_by is None:
        raise ValueError("group_by is required when mode is aggregate")
    if mode == "rows" and group_by is not None:
        raise ValueError("group_by is only used when mode is aggregate")

    if mode == "aggregate" and cursor is not None:
        raise ValueError("cursor is only used when mode is rows: aggregate reads every match")

    if custom_fields and exclude_custom_fields:
        raise ValueError(
            "exclude_custom_fields cannot be combined with custom_fields: the filter reads them"
        )

    fingerprint = search_fingerprint(
        "search_opportunities",
        {
            "representative": representative,
            "is_open": is_open,
            "stage": stage,
            "product": product,
            "custom_fields": custom_fields,
            "exclude_custom_fields": exclude_custom_fields,
            "mode": mode,
            "group_by": group_by,
            "fields": fields,
        },
    )
    start_offset = (
        0
        if cursor is None
        else SearchCursor.decode(cursor, fingerprint=fingerprint, collections=1).offsets[0]
    )
    products = tuple(product or ())
    predicates = _predicates(custom_fields)
    logger.info(
        "opportunities.search.start",
        extra={
            "representative": representative,
            "mode": mode,
            "stage": stage,
            "product": products,
            "custom_fields": len(predicates),
            "exclude_custom_fields": exclude_custom_fields,
            "start_offset": start_offset,
        },
    )
    return await search_opportunities_query.run(
        representative=representative,
        is_open=is_open,
        stage=stage,
        products=products,
        custom_fields=predicates,
        exclude_custom_fields=exclude_custom_fields,
        mode=mode,
        group_by=group_by,
        fields=(frozenset(fields) if fields else _DEFAULT_FIELDS) | {"id"},
        result_size=search_config.result_size,
        start_offset=start_offset,
        fingerprint=fingerprint,
    )
