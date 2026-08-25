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
omits the name, rather than being dropped or guessed at.

**Records are validated one at a time.** The fetch pages with the attributes left as a plain
dict, and `OpportunityResponse` then reads each record's own attributes through its aliases. A
typed page schema would deserialize the whole page in one pass, so one malformed record — a
`regularCustomFieldValues` that is not a list, say — would fail every opportunity the party has.
Here it is warned about and dropped on its own.
"""

import asyncio
import logging
from collections.abc import Awaitable, Iterable, Mapping, Sequence
from datetime import date
from typing import Literal
from urllib.parse import quote

from pydantic import TypeAdapter, ValidationError

from backstop_mcp.backstop_client import (
    BackstopApiResource,
    BackstopClient,
    ResourceRef,
    follow_included,
    included_by_type,
)
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.opportunities.api_responses import OpportunityStageAttributes
from backstop_mcp.features.opportunities.internal_dto import OpportunityStageDto
from backstop_mcp.features.opportunities.responses import (
    OpportunityFetchResponse,
    OpportunityResponse,
    StageChangeResponse,
)

logger = logging.getLogger(__name__)

_PAGE_SIZE = 100
_INCLUDE = "stage,stageHistory"
_STAGE = "stage"
_STAGE_HISTORY = "stageHistory"
_STAGE_TYPE = "opportunity-stages"

_RawAttributes: TypeAdapter[dict[str, object]] = TypeAdapter(dict[str, object])

type OpportunityStatus = Literal["open", "closed", "all"]
type OpportunityResource = BackstopApiResource[dict[str, object]]


def _stage_ref_id(value: object) -> str | None:
    """The stage id a history entry's inline pointer carries, or None when it carries none.

    `ResourceRef.resource_id` is required, correctly — a reference nobody can resolve is not a
    reference — but failing on it would discard the whole history entry, its `effectiveDate` with
    it. A stage this response cannot identify is reported with the name omitted beside the move
    that happened, exactly as one the vocabulary can no longer name is.
    """
    try:
        return ResourceRef.model_validate(value).resource_id
    except ValidationError:
        return None


def stage_names_from_included(included: Sequence[dict[str, object]]) -> dict[str, str]:
    """Stage id to name for every `opportunity-stages` resource side-loaded with the response.

    Selected by JSON:API `type` rather than followed from linkage, because the stages a history
    entry points at are reached through an inline `ResourceRef` that nothing on the primary
    resource links to. An unnamed or unreadable row is skipped: naming a stage is the only thing
    this index is for.
    """
    names: dict[str, str] = {}
    for raw in included_by_type(included, _STAGE_TYPE):
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
    vocabulary: Mapping[str, OpportunityStageDto],
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


def _matches_status(opportunity: OpportunityResponse, status: OpportunityStatus) -> bool:
    """Whether one deal belongs in an answer asked for `status`.

    A deal whose `isOpen` did not arrive matches neither `open` nor `closed` — it is as wrong to
    file it under one as the other — and is only returned by `all`.
    """
    if status == "all":
        return True
    if opportunity.is_open is None:
        return False
    return opportunity.is_open is (status == "open")


def _date_entered_order_key(opportunity: OpportunityResponse) -> tuple[bool, date]:
    """Sort key placing the most recent stage move first under `reverse=True`.

    The leading flag keeps a deal with no `date_entered_current_stage` last rather than letting
    it lead the list as an artificially old date would.
    """
    entered = opportunity.date_entered_current_stage
    return (entered is not None, entered or date.min)


def _order_by_date_entered(
    opportunities: Iterable[OpportunityResponse],
) -> tuple[OpportunityResponse, ...]:
    """Deals newest-first by the day they entered their current stage."""
    return tuple(sorted(opportunities, key=_date_entered_order_key, reverse=True))


def stage_history(
    resource: OpportunityResource,
    *,
    included: Sequence[dict[str, object]],
    side_loaded: Mapping[str, str],
    vocabulary: Mapping[str, OpportunityStageDto],
) -> tuple[StageChangeResponse, ...]:
    """One deal's stage moves, in the order Backstop links them.

    The entries come back as raw dicts and only their `attributes` are read: an
    `opportunity-stage-history` resource carries `"relationships": null`, which
    `BackstopApiResource` rejects as "input should be a valid dictionary". `StageChangeResponse`
    reads `effectiveDate` off those attributes itself, with the entry's inline stage pointer
    replaced by the name and id resolved from it. An entry whose attributes are unreadable is
    dropped on its own so one bad row does not cost the trail.
    """
    changes: list[StageChangeResponse] = []
    for raw in follow_included(included, resource, _STAGE_HISTORY):
        try:
            attributes = _RawAttributes.validate_python(raw.get("attributes"))
        except ValidationError as exc:
            logger.warning(
                "opportunities.stage_history.unreadable",
                extra={"opportunity_id": resource.id, "entry_id": raw.get("id")},
                exc_info=exc,
            )
            continue
        stage_id = _stage_ref_id(attributes.get(_STAGE))
        changes.append(
            StageChangeResponse.model_validate(
                {
                    **attributes,
                    "stage": resolve_stage_name(
                        stage_id, side_loaded=side_loaded, vocabulary=vocabulary
                    ),
                    "stage_id": stage_id,
                }
            )
        )
    return tuple(changes)


def _project_opportunities(
    resources: Sequence[OpportunityResource],
    *,
    included: Sequence[dict[str, object]],
    vocabulary: Mapping[str, OpportunityStageDto],
) -> tuple[OpportunityResponse, ...]:
    """Project the fetched resources, indexing the side-loaded stages once for all of them.

    `included` is every side-load accumulated across the whole walk, so a stage side-loaded with
    the first page still names a deal that arrived on the last.

    A record the response model cannot read is warned about and dropped on its own — the party's
    other deals are still an answer, and this is the whole reason the fetch does not hand the
    page a typed schema.
    """
    side_loaded = stage_names_from_included(included)
    projected: list[OpportunityResponse] = []
    for resource in resources:
        try:
            stage_id = current_stage_id(resource)
            projected.append(
                OpportunityResponse.from_resource(
                    resource,
                    stage=resolve_stage_name(
                        stage_id, side_loaded=side_loaded, vocabulary=vocabulary
                    ),
                    stage_id=stage_id,
                    stage_history=stage_history(
                        resource,
                        included=included,
                        side_loaded=side_loaded,
                        vocabulary=vocabulary,
                    ),
                )
            )
        except ValidationError as exc:
            logger.warning(
                "opportunities.record.unreadable",
                extra={"opportunity_id": resource.id},
                exc_info=exc,
            )
    return tuple(projected)


async def await_vocabulary(
    vocabulary: Mapping[str, OpportunityStageDto] | Awaitable[Mapping[str, OpportunityStageDto]],
) -> dict[str, OpportunityStageDto]:
    """The vocabulary mapping, whether the caller already had it or is still fetching it.

    A Mapping is returned as a new dict; an awaitable is awaited. `fetch_opportunities` gathers
    this with the sub-collection page so the tool can pass `stages_service.get(client)` and the
    two HTTP calls run together.
    """
    if isinstance(vocabulary, Mapping):
        return dict(vocabulary)
    return dict(await vocabulary)


async def fetch_opportunities(
    client: BackstopClient,
    *,
    segment: SearchType,
    entity_id: str,
    status: OpportunityStatus = "all",
    vocabulary: Mapping[str, OpportunityStageDto] | Awaitable[Mapping[str, OpportunityStageDto]],
) -> OpportunityFetchResponse:
    """Every opportunity for one party, `status`-filtered and newest stage move first.

    Walks the party's whole sub-collection: both the filter and the ordering are over the
    complete set, so a partial fetch would answer the wrong question.

    Takes the stage vocabulary as a mapping or as an awaitable that produces one, so the caller
    decides when that fetch happens — and can overlap it with this page walk by passing the
    in-flight coroutine. Either failure fails the call: a pipeline that silently omits stages
    is worse than an error.
    """
    page, resolved_vocabulary = await asyncio.gather(
        client.paginate(
            f"/{segment}/{quote(entity_id, safe='')}/opportunities",
            # Attributes left as a plain dict so each record is validated on its own — see the
            # module docstring: a typed page schema fails every opportunity over one malformed
            # record.
            schema=BackstopApiResource[dict[str, object]],
            params={"include": _INCLUDE},
            # Explicitly unbounded: `paginate` caps at 10_000 records by default, so passing
            # nothing would reintroduce a cap that never announces itself.
            max_records=None,
            page_size=_PAGE_SIZE,
        ),
        await_vocabulary(vocabulary),
    )
    fetched = _project_opportunities(
        page.items, included=page.included, vocabulary=resolved_vocabulary
    )
    selected = _order_by_date_entered(
        opportunity for opportunity in fetched if _matches_status(opportunity, status)
    )
    result = OpportunityFetchResponse(
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
