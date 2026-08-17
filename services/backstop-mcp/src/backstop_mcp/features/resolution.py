"""One resolution algebra, one ambiguity policy, shared by every name-to-record lookup.

Party resolution (`party_resolver`) answers "the user said X — which record is that?"
A later resolver has an obvious shape to adopt.

Vocabulary, used identically on the wire and in the internal types:

* `query` — what the user said.
* `scope`  — the collection the query was resolved against (`organizations`, `people`, ...).
* `candidates` — the plausible matches, when there is more than one.

The policy itself:

1. Exactly one match → `Resolved`. Callers echo the resolved identity so a wrong resolution is
   visible rather than silent.
2. Several matches, single-entity call → elicit a choice from the user.
3. Several matches inside a batch → resolve what resolves and return **one** combined payload,
   so the model asks once rather than N times.
4. Client can't elicit (or declines/cancels) → degrade from (2) to the same structured payload
   as (3).
5. Zero matches → `NotFound`, naming the query that was actually used.
"""

import logging
from collections import Counter
from collections.abc import Callable, Sequence
from typing import Annotated, ClassVar, Literal, Protocol, cast

from fastmcp import Context
from fastmcp.server.elicitation import AcceptedElicitation
from mcp.server.elicitation import CancelledElicitation, DeclinedElicitation
from mcp.types import ClientCapabilities, ElicitationCapability
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


# --- Internal algebra -----------------------------------------------------------------------


class Candidate[T](BaseModel):
    """One plausible match.

    `key` is a stable identity used to map an elicitation answer back to `value`; `label` is
    what the user sees. `value` is whatever the calling subsystem resolves to.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    key: str
    label: str
    value: T


class Resolved[T](BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    value: T
    status: Literal["resolved"] = "resolved"


class Ambiguous[T](BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    query: str
    scope: str
    candidates: tuple[Candidate[T], ...]
    status: Literal["ambiguous"] = "ambiguous"


class NotFound(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    query: str
    scope: str
    status: Literal["not_found"] = "not_found"


type Resolution[T] = Annotated[Resolved[T] | Ambiguous[T] | NotFound, Field(discriminator="status")]
type Unresolved[T] = Ambiguous[T] | NotFound


def from_candidates[T](
    candidates: Sequence[Candidate[T]], *, query: str, scope: str
) -> Resolution[T]:
    """Apply steps 1 and 5 of the policy to a raw candidate list."""
    if not candidates:
        return NotFound(query=query, scope=scope)
    if len(candidates) == 1:
        return Resolved(value=candidates[0].value)
    return Ambiguous(query=query, scope=scope, candidates=tuple(candidates))


# --- Batch algebra (policy step 3) ----------------------------------------------------------


class BatchResolvedItem[T](BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    index: int
    value: T


class BatchUnresolvedItem[T](BaseModel):
    """One unresolved batch input. Empty `candidates` means not found."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    index: int
    query: str
    scope: str
    candidates: tuple[Candidate[T], ...]


class BatchResolved[T](BaseModel):
    """Every input resolved. `values` is ordered by input index."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    values: tuple[T, ...]
    status: Literal["resolved"] = "resolved"


class BatchAmbiguous[T](BaseModel):
    """At least one input did not resolve; includes the ones that did, for continuity."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    unresolved: tuple[BatchUnresolvedItem[T], ...]
    resolved: tuple[BatchResolvedItem[T], ...]
    status: Literal["ambiguous"] = "ambiguous"


type BatchResolution[T] = Annotated[
    BatchResolved[T] | BatchAmbiguous[T], Field(discriminator="status")
]


def collect_batch[T](
    outcomes: Sequence[tuple[str, Resolution[T]]],
) -> BatchResolution[T]:
    """Fold per-item resolutions into one batch outcome.

    Each entry pairs the query used with its resolution. A single combined payload is returned
    whenever anything failed to resolve, so the model prompts once for the whole batch.
    """
    resolved: list[BatchResolvedItem[T]] = []
    unresolved: list[BatchUnresolvedItem[T]] = []

    for index, (query, outcome) in enumerate(outcomes):
        if isinstance(outcome, Resolved):
            resolved.append(BatchResolvedItem(index=index, value=outcome.value))
        elif isinstance(outcome, Ambiguous):
            unresolved.append(
                BatchUnresolvedItem(
                    index=index,
                    query=outcome.query,
                    scope=outcome.scope,
                    candidates=outcome.candidates,
                )
            )
        else:
            unresolved.append(
                BatchUnresolvedItem(index=index, query=query, scope=outcome.scope, candidates=())
            )

    if unresolved:
        return BatchAmbiguous(unresolved=tuple(unresolved), resolved=tuple(resolved))
    return BatchResolved(values=tuple(item.value for item in resolved))


# --- Elicitation (policy steps 2 and 4) -----------------------------------------------------


class _ClientCapabilityChecker(Protocol):
    def check_client_capability(self, capability: ClientCapabilities) -> bool: ...


class _RequestContext(Protocol):
    @property
    def session(self) -> _ClientCapabilityChecker: ...


def client_supports_elicitation(ctx: Context) -> bool:
    """Whether the connected client advertised the elicitation capability.

    Uses FastMCP's public `request_context` (the same accessor `Context.client_supports_extension`
    uses) rather than reaching for private attributes. No request context means no session to
    prompt through, so the answer is False and the caller degrades to a structured payload —
    failing toward "ask the model" rather than toward a crash.
    """
    request_context = cast("_RequestContext | None", getattr(ctx, "request_context", None))
    if request_context is None:
        return False
    try:
        return bool(
            request_context.session.check_client_capability(
                ClientCapabilities(elicitation=ElicitationCapability())
            )
        )
    except Exception as exc:
        logger.warning(
            "resolution.elicit.capability_check_failed",
            extra={"error": str(exc)},
        )
        return False


def _unique_labels[T](candidates: Sequence[Candidate[T]]) -> dict[str, Candidate[T]]:
    """Collision-free display labels for an elicit enum.

    `Candidate.key` is unique, so colliding bare labels are disambiguated with `[key]` —
    both sides of a collision get the key suffix so the user sees equally-qualified options.
    """
    seen = Counter(candidate.label for candidate in candidates)
    return {
        (
            candidate.label
            if seen[candidate.label] == 1
            else f"{candidate.label} [{candidate.key}]"
        ): candidate
        for candidate in candidates
    }


async def elicit_choice[T](
    ctx: Context,
    ambiguous: Ambiguous[T],
    *,
    prompt: str,
) -> Resolution[T]:
    """Ask the user to pick one candidate, degrading to `ambiguous` if that isn't possible.

    Returns the original `Ambiguous` unchanged whenever a user-visible choice can't be
    obtained — unsupported client, declined, cancelled, or any transport failure — so the
    caller's single "not resolved" branch covers every degradation path.
    """
    assert len(ambiguous.candidates) >= 2, "elicit_choice requires at least two candidates"

    if not client_supports_elicitation(ctx):
        logger.info(
            "resolution.elicit.skipped",
            extra={"reason": "client lacks elicitation capability"},
        )
        return ambiguous

    by_label = _unique_labels(ambiguous.candidates)
    try:
        result = await ctx.elicit(message=prompt, response_type=list(by_label))
    except Exception as exc:
        logger.warning("resolution.elicit.degraded", extra={"error": str(exc)})
        return ambiguous

    if isinstance(result, AcceptedElicitation):
        chosen = by_label.get(result.data)
        if chosen is None:
            logger.warning("resolution.elicit.unknown_choice")
            return ambiguous
        return Resolved(value=chosen.value)

    assert isinstance(result, (DeclinedElicitation, CancelledElicitation))
    return ambiguous


# --- LLM-facing response models -------------------------------------------------------------


class CandidateResponse(BaseModel):
    """Base shape every candidate response shares. Subsystems subclass to add their fields."""

    key: str = Field(
        description=(
            "Stable identity for this candidate. Echo it only as part of picking this option "
            "— it is not a Backstop party id."
        )
    )
    label: str = Field(
        description="What to show the user when asking which record they meant."
    )


# Generic rather than "subclass and narrow `candidates`": a mutable `list[...]` field is
# invariant, so a subclass redeclaring it as `list[PartyCandidateResponse]` is genuinely
# unsound. Parameterizing gives each subsystem a distinct concrete model — pydantic resolves
# the subscript to a real class, which is also what FastMCP needs for tool output schemas.
class AmbiguousResponse[CandidateT: CandidateResponse](BaseModel):
    """Returned when a query matched several records and no single one could be chosen."""

    status: Literal["ambiguous"] = Field(
        default="ambiguous",
        description="Always 'ambiguous': more than one record matched and none was chosen.",
    )
    query: str = Field(description="The search text that produced these candidates.")
    scope: str = Field(
        description=(
            "Collection the query was resolved against, e.g. 'organizations' or 'people'."
        )
    )
    candidates: list[CandidateT] = Field(
        default_factory=list,
        description=(
            "The matching records. Show `label` to the user, then retry with that candidate's "
            "`id` and `search_type` — never invent an id."
        ),
    )


class NotFoundResponse(BaseModel):
    """Returned when a query matched no records. `query` is the exact term searched for."""

    status: Literal["not_found"] = Field(
        default="not_found",
        description="Always 'not_found': no record matched `query` in `scope`.",
    )
    query: str = Field(description="The search text that matched nothing.")
    scope: str = Field(
        description=(
            "Collection the query was resolved against, e.g. 'organizations' or 'people'."
        )
    )


class BatchUnresolvedResponse[CandidateT: CandidateResponse](BaseModel):
    """One batch input that did not resolve, with the candidates (if any) for that input."""

    index: int = Field(description="0-based index of this input in the original batch.")
    query: str = Field(description="The search text for this input.")
    scope: str = Field(description="Collection this input was resolved against.")
    candidates: list[CandidateT] = Field(
        default_factory=list,
        description="Matching records for this input; empty when nothing matched.",
    )


class BatchResolvedResponse[ResolvedT](BaseModel):
    """One batch input that did resolve, kept so the model can continue with it."""

    index: int = Field(description="0-based index of this input in the original batch.")
    value: ResolvedT = Field(description="The identity this input settled on.")


class BatchAmbiguousResponse[CandidateT: CandidateResponse, ResolvedT](BaseModel):
    """One combined payload for a batch where at least one input didn't resolve.

    `resolved` carries the inputs that did settle (policy step 3), so the model can keep those
    and ask once about the rest — dropping them would force re-resolution of work already done.
    """

    status: Literal["ambiguous"] = Field(
        default="ambiguous",
        description="Always 'ambiguous': at least one input in the batch did not resolve.",
    )
    unresolved: list[BatchUnresolvedResponse[CandidateT]] = Field(
        default_factory=list,
        description="Inputs that did not settle, each with its own candidates.",
    )
    resolved: list[BatchResolvedResponse[ResolvedT]] = Field(
        default_factory=list,
        description="Inputs that did settle — keep these rather than re-resolving them.",
    )


type ToCandidateResponse[T, CandidateT] = Callable[[Candidate[T]], CandidateT]
type ToResolvedResponse[T, ResolvedT] = Callable[[T], ResolvedT]


def unresolved_response[T, CandidateT: CandidateResponse](
    result: Unresolved[T],
    *,
    ambiguous_model: type[AmbiguousResponse[CandidateT]],
    to_candidate: ToCandidateResponse[T, CandidateT],
) -> AmbiguousResponse[CandidateT] | NotFoundResponse:
    """Convert a non-`Resolved` outcome into this subsystem's standard tool response.

    Callers short-circuit on this before doing any tool-specific fetch: there is nothing left
    to look up until the caller either picks a candidate or narrows the query.
    """
    if isinstance(result, NotFound):
        return NotFoundResponse(query=result.query, scope=result.scope)
    return ambiguous_model(
        query=result.query,
        scope=result.scope,
        candidates=[to_candidate(candidate) for candidate in result.candidates],
    )


def batch_ambiguous_response[T, CandidateT: CandidateResponse, ResolvedT](
    result: BatchAmbiguous[T],
    *,
    batch_model: type[BatchAmbiguousResponse[CandidateT, ResolvedT]],
    unresolved_model: type[BatchUnresolvedResponse[CandidateT]],
    resolved_model: type[BatchResolvedResponse[ResolvedT]],
    to_candidate: ToCandidateResponse[T, CandidateT],
    to_resolved: ToResolvedResponse[T, ResolvedT],
) -> BatchAmbiguousResponse[CandidateT, ResolvedT]:
    """Convert a `BatchAmbiguous` into the wire payload, including already-resolved items."""
    return batch_model(
        unresolved=[
            unresolved_model(
                index=item.index,
                query=item.query,
                scope=item.scope,
                candidates=[to_candidate(candidate) for candidate in item.candidates],
            )
            for item in result.unresolved
        ],
        resolved=[
            resolved_model(index=item.index, value=to_resolved(item.value))
            for item in result.resolved
        ],
    )
