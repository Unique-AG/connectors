"""`search_opportunities`: firm-wide pipeline walk over `GET /opportunities`.

`filter[representative.name][eq]` is the only representative filter Backstop accepts, and it is
the deal-level field, which may be blank. `representative` here matches the investor
organization's representative, in memory. Every filter is client-side.
"""

import logging
from collections.abc import Sequence
from typing import Annotated, Literal

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

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
                "Backstop **login** (`user_name` from list_system_users), not a display name. "
                "Keeps deals whose investor organization is represented by that login, "
                "including deals with no representative on the deal "
                "itself. It does not match the deal-level representative. A display name "
                "such as 'Jane Doe' returns 0 rows. Applied after the server-side read."
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
                "Several values are OR, so several vehicles can be one walk, e.g. "
                '["NWON", "NWOF"]. Resolve names with get_product '
                "first when unsure. This is not a strategy label. Strategy-like words are "
                "usually custom fields — filter those with `custom_fields`. "
                "Applied after the server-side read."
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
                "(the fields a table is grouped or labelled by), so one walk answers the table. "
                "Leave this "
                "false. Set it true only to retry a call that timed out, to see whether "
                "reading the custom fields is what made it slow. Refused together with "
                "`custom_fields`, which needs them."
            )
        ),
    ] = False,
    mode: Annotated[
        SearchMode,
        Field(description="`rows` (default) or `aggregate` for counts without row bodies."),
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
                "deals — it is off by default so a wide walk stays cheap."
            ),
        ),
    ] = None,
    search_opportunities_query: SearchOpportunitiesQuery = Depends(
        get_search_opportunities_query_factory
    ),
) -> SearchOpportunitiesResolvedResponse:
    """Walk the firm-wide pipeline.

    `product` matches the linked fund. A short name matches exactly; a display-name
    substring matches every vehicle whose name contains it. Several `product` values are
    OR. `mode="aggregate", group_by="product"` counts that linked fund. The chip may be
    empty, and then every open deal is `(unattributed)`.

    Business terms such as strategy, status, tier, investor type, or region are usually
    custom fields. Call list_custom_fields for organizations and opportunities, pick the
    field whose name or options match the user's words, then filter by its definition id
    and the exact option. If no field or several fields could be it, ask which one. Say
    which field and options you used. The other table columns are on each row's
    `custom_field_values`. If a call times out, retry once with `exclude_custom_fields=true`
    to see whether reading them is the cause; otherwise leave it false. That walk is the
    full match. Do not select deals because the name contains the word, and do not call
    get_opportunities_by_ids to re-read fields this walk already returned.

    `is_open` means the deal is still in the pipeline. `representative` matches the
    investor organization's representative login (`investor_representative` on each row),
    not the deal-level field, which may be blank. Pass that **login** from
    list_system_users. A display name silently returns zero rows. Every filter is applied
    after the server-side read.
    `coverage.visible_count` is Backstop's total before those filters. An empty `rows`
    list means nothing matched.

    A stage-change question ("what moved stage since X") stays on this tool. Select
    `previous_stage` and `date_entered_current_stage` and keep rows whose
    `date_entered_current_stage` is inside the window, including deals that closed — do not
    pass `is_open`. Do not ask the user for those field names, and do not walk
    get_opportunities_by_ids for this question. Those two fields are the latest move per
    deal only; say so. `id` is always projected. `custom_fields_unavailable` means the
    catalog missed: stored values on this row are still the text Backstop sent, and
    get_opportunities_by_ids would not resolve types. Amounts are on this walk; select
    them with `fields`.

    For one party's deals, call get_opportunities instead — that is one cheap sub-collection,
    not this walk. This tool has no `party_id`. `mode=aggregate` with `group_by` answers a
    counting question without row bodies. Investor geography is on the `investor` chip (the
    include is a contacts resource).

    For deals with no activity in 30/60/90 days, pass each distinct `investor.id` and
    `investor.search_type` to get_last_activity_for_parties and bucket by its
    `days_since_last_activity`. Days in stage is not activity.

    Call like: {"representative": "jdoe", "is_open": true}
    Investor-organization representative: {"representative": "jdoe", "is_open": true,
    "fields": ["name", "stage", "requested_amount", "investor", "investor_representative",
    "representative"]}
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

    if custom_fields and exclude_custom_fields:
        raise ValueError(
            "exclude_custom_fields cannot be combined with custom_fields: the filter reads them"
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
    )
