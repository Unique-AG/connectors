"""One party's opportunities: one paginated sub-collection fetch, projected, filtered, ordered.

Everything below was measured against a live instance rather than read from the swagger, and
several of the facts contradict the obvious reading of the API.

**Filtering and ordering are ours.** `filter[isOpen][eq]=true` is a 400 on this endpoint (only
five documented filter fields work), and `sort=` is *accepted and silently ignored* on party
sub-collections — `sort=modifiedTimestamp` and `sort=-modifiedTimestamp` returned byte-identical
records. So `status` and the `dateEnteredCurrentStage` ordering are applied here, in memory, over
the whole set. That is also why nothing here is cursored: paging outward would hand a party whose
open deals sit on page 3 an authoritative-looking empty answer for `status="open"`, and would order
each page correctly but the list wrongly. The whole `links.next` chain is walked instead, with no
cap: across 513 investors a party has p50 = 1 opportunity, p90 = 4 and 33 at most, so a cap would
never fire — and with no cursor exposed, one that did would leave the caller no way to the rest.

**`previousStage` is a trap.** It is a plain string naming the stage the deal just *left*, and it
is absent until the deal has moved at all. So `include=stage` is the only way to name the current
stage, and the one stage-shaped attribute on the record would actively mislead.

**Stage history is a relationship whose entries are not.** `stage` and `stageHistory` are proper
JSON:API relationships, but a side-loaded `opportunity-stage-history` entry points at its own
stage through `attributes.stage` in Backstop's *inline* `{resourceType, resourceId, resourceLink}`
format — `ResourceRef`, not linkage `follow_included` can walk. Those entries also arrive with
`"relationships": null` rather than `{}`, which `BackstopApiResource` rejects outright, so they
are read as the raw dicts they arrive as.

**Side-loading does not cover the vocabulary.** 45 history entries on one party referenced 6
distinct stage ids while only 3 arrived in `included`. Every stage id is therefore resolved
against this response first and the cached vocabulary second; one in neither keeps its id and
reports a null name, rather than being dropped or guessed at.
"""

import logging
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import Annotated, ClassVar, Literal
from urllib.parse import quote

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
)

from backstop_mcp.backstop_client import (
    BackstopApiCollectionDocument,
    BackstopApiResource,
    BackstopClient,
    follow_included,
    included_by_type,
)
from backstop_mcp.dates import LenientDate
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.includes import ResourceRef
from backstop_mcp.features.opportunities.responses import (
    OpportunityResponse,
    StageChangeResponse,
)
from backstop_mcp.features.opportunities.stages import (
    OpportunityStage,
    OpportunityStageAttributes,
)

logger = logging.getLogger(__name__)

_PAGE_SIZE = 100
_INCLUDE = "stage,stageHistory"
_STAGE = "stage"
_STAGE_HISTORY = "stageHistory"
_STAGE_TYPE = "opportunity-stages"

_StrippedStr = Annotated[str, StringConstraints(strip_whitespace=True)]

type OpportunityStatus = Literal["open", "closed", "all"]


class OpportunityAttributes(BaseModel):
    """Wire shape for `opportunities` attributes — the subset a pipeline question needs.

    Every field is optional for the same reason `OpportunityStageAttributes`' are: a page is
    deserialized in one pass, so a required field would fail a party's whole pipeline over one
    malformed record. `isOpen`, `dateEnteredCurrentStage` and `daysInCurrentStage` were in fact
    never null across all 1206 opportunities in the instance this was built against;
    `regularCustomFieldValues` was not measured that way, so an explicit null there reads as no
    custom fields rather than as a bad record.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    name: _StrippedStr | None = None
    previous_stage: _StrippedStr | None = Field(default=None, alias="previousStage")
    is_open: bool | None = Field(default=None, alias="isOpen")
    probability: float | None = None
    requested_amount: float | None = Field(default=None, alias="requestedAmount")
    allocated_amount: float | None = Field(default=None, alias="allocatedAmount")
    currency: _StrippedStr | None = Field(default=None, alias="currencyCode")
    expected_investment_date: LenientDate = Field(default=None, alias="expectedInvestmentDate")
    closed_date: LenientDate = Field(default=None, alias="closedDate")
    days_open: int | None = Field(default=None, alias="daysOpen")
    days_in_current_stage: int | None = Field(default=None, alias="daysInCurrentStage")
    date_entered_current_stage: LenientDate = Field(default=None, alias="dateEnteredCurrentStage")
    custom_field_values: list[dict[str, object]] | None = Field(
        default=None, alias="regularCustomFieldValues"
    )


def parse_stage_ref(value: object) -> ResourceRef | None:
    """Read a history entry's inline stage pointer, or None when it carries no usable id.

    `ResourceRef.resource_id` is required, correctly — a reference nobody can resolve is not a
    reference — but validating the field would discard the whole history entry, its
    `effective_date` with it. A stage this response cannot identify is reported as a null name
    beside the move that happened, exactly as one the vocabulary can no longer name is.
    """
    try:
        return ResourceRef.model_validate(value)
    except ValidationError:
        return None


class StageHistoryAttributes(BaseModel):
    """Wire shape for one side-loaded `opportunity-stage-history` entry's attributes.

    `stage` is an inline `ResourceRef`, not JSON:API linkage — see the module docstring. The
    entry's `relationships` is never read, which is what keeps its literal `null` harmless.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    stage: Annotated[ResourceRef | None, BeforeValidator(parse_stage_ref)] = None
    effective_date: LenientDate = Field(default=None, alias="effectiveDate")


type OpportunityResource = BackstopApiResource[OpportunityAttributes]
type OpportunityDocument = BackstopApiCollectionDocument[OpportunityAttributes]


class OpportunityFetchResult(BaseModel):
    """One party's opportunities after filtering and ordering, plus what the whole set says.

    `total` and the two counts are over everything fetched — the party's complete set, since the
    fetch walks their whole sub-collection — so `status="open"` still reports how many closed
    deals exist.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    opportunities: tuple[OpportunityResponse, ...] = Field(
        description=(
            "The deals matching the requested status, newest first by the day each entered its "
            + "current stage."
        )
    )
    total: int = Field(
        description=(
            "Every opportunity fetched for this party, before filtering by status — so the "
            + "number they have in total. Counted here rather than read from Backstop's own "
            + "`meta.totalResourceCount`."
        )
    )
    open_count: int = Field(
        description=(
            "How many of those are open, whatever status was asked for — so an answer about "
            + "open deals still says how many exist."
        )
    )
    closed_count: int = Field(
        description="How many of those are closed, counted the same way as `open_count`."
    )


def stage_names_from_included(document: OpportunityDocument) -> dict[str, str]:
    """Stage id to name for every `opportunity-stages` resource side-loaded with the response.

    Selected by JSON:API `type` rather than followed from linkage, because the stages a history
    entry points at are reached through an inline `ResourceRef` that nothing on the primary
    resource links to. An unnamed or unreadable row is skipped: naming a stage is the only thing
    this index is for.
    """
    names: dict[str, str] = {}
    for raw in included_by_type(document, _STAGE_TYPE):
        stage_id = raw.get("id")
        if not isinstance(stage_id, str) or not stage_id.strip():
            continue
        try:
            attributes = OpportunityStageAttributes.model_validate(raw.get("attributes"))
        except ValidationError as exc:
            logger.warning(
                "opportunities.side_loaded_stage.unreadable",
                extra={"stage_id": stage_id},
                exc_info=exc,
            )
            continue
        if attributes.name:
            names[stage_id.strip()] = attributes.name
    return names


def resolve_stage_name(
    stage_id: str | None,
    *,
    side_loaded: Mapping[str, str],
    vocabulary: Mapping[str, OpportunityStage],
) -> str | None:
    """Name a stage from this response's side-loads, then from the cached vocabulary.

    `None` when the id is in neither, which the caller reports alongside the id rather than
    dropping the entry: only 3 of the 6 stages one party's history referenced arrived in
    `included`, and a stage the instance has since retired is missing from both.
    """
    if stage_id is None:
        return None
    side_loaded_name = side_loaded.get(stage_id)
    if side_loaded_name is not None:
        return side_loaded_name
    known = vocabulary.get(stage_id)
    return known.name if known is not None else None


def current_stage_id(resource: OpportunityResource) -> str | None:
    """The deal's current stage id, stripped to match how both stage indexes are keyed.

    `BackstopRelationshipRef.id` carries no `StringConstraints`, while `stage_names_from_included`
    keys on a stripped id and the vocabulary's come from `BackstopApiResource`, which strips its
    own. A padded linkage id would otherwise miss both and report a resolvable stage as unnamed.
    """
    return next(
        (
            stripped
            for related_id in resource.related_ids(_STAGE)
            if (stripped := related_id.strip())
        ),
        None,
    )


def matches_status(opportunity: OpportunityResponse, status: OpportunityStatus) -> bool:
    """Whether one deal belongs in an answer asked for `status`.

    A deal whose `isOpen` did not arrive matches neither `open` nor `closed` — it is as wrong to
    file it under one as the other — and is only returned by `all`.
    """
    if status == "all":
        return True
    if opportunity.is_open is None:
        return False
    return opportunity.is_open is (status == "open")


def date_entered_order_key(opportunity: OpportunityResponse) -> tuple[bool, date]:
    """Sort key placing the most recent stage move first under `reverse=True`.

    The leading flag keeps a deal with no `date_entered_current_stage` last rather than letting
    it lead the list as an artificially old date would.
    """
    entered = opportunity.date_entered_current_stage
    return (entered is not None, entered or date.min)


def order_by_date_entered(
    opportunities: Iterable[OpportunityResponse],
) -> tuple[OpportunityResponse, ...]:
    """Deals newest-first by the day they entered their current stage."""
    return tuple(sorted(opportunities, key=date_entered_order_key, reverse=True))


def stage_history(
    resource: OpportunityResource,
    *,
    document: OpportunityDocument,
    side_loaded: Mapping[str, str],
    vocabulary: Mapping[str, OpportunityStage],
) -> tuple[StageChangeResponse, ...]:
    """One deal's stage moves, in the order Backstop links them.

    The entries come back as raw dicts and only their `attributes` are validated: an
    `opportunity-stage-history` resource carries `"relationships": null`, which
    `BackstopApiResource` rejects as "input should be a valid dictionary". An entry whose
    attributes are unreadable is dropped on its own so one bad row does not cost the trail.
    """
    changes: list[StageChangeResponse] = []
    for raw in follow_included(document, resource, _STAGE_HISTORY):
        try:
            attributes = StageHistoryAttributes.model_validate(raw.get("attributes"))
        except ValidationError as exc:
            logger.warning(
                "opportunities.stage_history.unreadable",
                extra={"opportunity_id": resource.id, "entry_id": raw.get("id")},
                exc_info=exc,
            )
            continue
        stage_id = attributes.stage.resource_id if attributes.stage is not None else None
        changes.append(
            StageChangeResponse(
                stage=resolve_stage_name(stage_id, side_loaded=side_loaded, vocabulary=vocabulary),
                stage_id=stage_id,
                effective_date=attributes.effective_date,
            )
        )
    return tuple(changes)


def to_opportunity_response(
    resource: OpportunityResource,
    *,
    document: OpportunityDocument,
    side_loaded: Mapping[str, str],
    vocabulary: Mapping[str, OpportunityStage],
) -> OpportunityResponse:
    """Project one `opportunities` resource, naming its current stage and its history."""
    attributes = resource.attributes
    stage_id = current_stage_id(resource)
    return OpportunityResponse(
        id=resource.id,
        name=attributes.name,
        stage=resolve_stage_name(stage_id, side_loaded=side_loaded, vocabulary=vocabulary),
        stage_id=stage_id,
        previous_stage=attributes.previous_stage,
        is_open=attributes.is_open,
        probability=attributes.probability,
        requested_amount=attributes.requested_amount,
        allocated_amount=attributes.allocated_amount,
        currency=attributes.currency,
        expected_investment_date=attributes.expected_investment_date,
        closed_date=attributes.closed_date,
        days_open=attributes.days_open,
        days_in_current_stage=attributes.days_in_current_stage,
        date_entered_current_stage=attributes.date_entered_current_stage,
        custom_field_values=tuple(attributes.custom_field_values or ()),
        stage_history=stage_history(
            resource, document=document, side_loaded=side_loaded, vocabulary=vocabulary
        ),
    )


def project_opportunities(
    resources: Sequence[OpportunityResource],
    *,
    document: OpportunityDocument,
    vocabulary: Mapping[str, OpportunityStage],
) -> tuple[OpportunityResponse, ...]:
    """Project the fetched resources, indexing the side-loaded stages once for all of them.

    `document` is the whole accumulated multi-page document, so a stage side-loaded with the first
    page still names a deal that arrived on the last.
    """
    side_loaded = stage_names_from_included(document)
    return tuple(
        to_opportunity_response(
            resource, document=document, side_loaded=side_loaded, vocabulary=vocabulary
        )
        for resource in resources
    )


async def fetch_opportunities(
    client: BackstopClient,
    *,
    segment: SearchType,
    entity_id: str,
    status: OpportunityStatus = "all",
    vocabulary: Mapping[str, OpportunityStage],
) -> OpportunityFetchResult:
    """Every opportunity for one party, `status`-filtered and newest stage move first.

    Walks the party's whole sub-collection: both the filter and the ordering are over the
    complete set, so a partial fetch would answer the wrong question.

    Takes the stage vocabulary already resolved rather than reaching for the service itself, so
    this stays a function of its arguments and the caller decides when that fetch happens.
    """
    page = await client.paginate(
        f"/{segment}/{quote(entity_id, safe='')}/opportunities",
        schema=BackstopApiResource[OpportunityAttributes],
        params={"include": _INCLUDE},
        # Explicitly unbounded: `paginate` caps at 10_000 records by default, so passing nothing
        # would reintroduce a cap that never announces itself.
        max_records=None,
        page_size=_PAGE_SIZE,
    )
    document = BackstopApiCollectionDocument[OpportunityAttributes](
        data=page.items, included=page.included
    )
    fetched = project_opportunities(document.data, document=document, vocabulary=vocabulary)
    selected = order_by_date_entered(
        opportunity for opportunity in fetched if matches_status(opportunity, status)
    )
    result = OpportunityFetchResult(
        opportunities=selected,
        total=len(fetched),
        open_count=sum(1 for opportunity in fetched if opportunity.is_open is True),
        closed_count=sum(1 for opportunity in fetched if opportunity.is_open is False),
    )
    logger.info(
        "opportunities.fetched",
        extra={
            "segment": segment,
            "entity_id": entity_id,
            "status": status,
            "total": result.total,
            "returned": len(result.opportunities),
        },
    )
    return result
