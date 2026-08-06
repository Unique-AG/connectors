"""One resolution algebra, one ambiguity policy, shared by every name-to-record lookup.

Two subsystems answer "the user said X — which record is that?": party resolution
(`party_resolver`) and custom-field resolution (`custom_fields`). Both are instances of the
policy below, so a third resolver has an obvious shape to adopt.

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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, cast

from fastmcp import Context
from fastmcp.server.elicitation import AcceptedElicitation
from mcp.server.elicitation import CancelledElicitation, DeclinedElicitation
from mcp.types import ClientCapabilities, ElicitationCapability
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# --- Internal algebra -----------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate[T]:
    """One plausible match.

    `key` is a stable identity used to map an elicitation answer back to `value`; `label` is
    what the user sees. `value` is whatever the calling subsystem resolves to.
    """

    key: str
    label: str
    value: T


@dataclass(frozen=True)
class Resolved[T]:
    value: T
    status: Literal["resolved"] = "resolved"


@dataclass(frozen=True)
class Ambiguous[T]:
    query: str
    scope: str
    candidates: tuple[Candidate[T], ...]
    status: Literal["ambiguous"] = "ambiguous"


@dataclass(frozen=True)
class NotFound:
    query: str
    scope: str
    status: Literal["not_found"] = "not_found"


type Resolution[T] = Resolved[T] | Ambiguous[T] | NotFound
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


@dataclass(frozen=True)
class BatchResolvedItem[T]:
    index: int
    value: T


@dataclass(frozen=True)
class BatchUnresolvedItem[T]:
    """One unresolved batch input. Empty `candidates` means not found."""

    index: int
    query: str
    scope: str
    candidates: tuple[Candidate[T], ...]


@dataclass(frozen=True)
class BatchResolved[T]:
    """Every input resolved. `values` is ordered by input index."""

    values: tuple[T, ...]
    status: Literal["resolved"] = "resolved"


@dataclass(frozen=True)
class BatchAmbiguous[T]:
    """At least one input did not resolve; includes the ones that did, for continuity."""

    unresolved: tuple[BatchUnresolvedItem[T], ...]
    resolved: tuple[BatchResolvedItem[T], ...]
    status: Literal["ambiguous"] = "ambiguous"


type BatchResolution[T] = BatchResolved[T] | BatchAmbiguous[T]


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


def _unique_labels[T](
    candidates: Sequence[Candidate[T]],
) -> tuple[list[str], dict[str, Candidate[T]]]:
    """Build a collision-free label list, since an elicit enum needs distinct strings."""
    by_label: dict[str, Candidate[T]] = {}
    labels: list[str] = []
    for candidate in candidates:
        display = candidate.label
        if display in by_label:
            display = f"{candidate.label} [{candidate.key}]"
            suffix = 2
            while display in by_label:
                display = f"{candidate.label} [{candidate.key}] #{suffix}"
                suffix += 1
        by_label[display] = candidate
        labels.append(display)
    assert len(labels) == len(set(labels))
    return labels, by_label


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

    labels, by_label = _unique_labels(ambiguous.candidates)
    try:
        result = await ctx.elicit(message=prompt, response_type=labels)
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


class CandidateEcho(BaseModel):
    """Base shape every candidate echo shares. Subsystems subclass it to add their own fields."""

    key: str
    label: str


# Generic rather than "subclass and narrow `candidates`": a mutable `list[...]` field is
# invariant, so a subclass redeclaring it as `list[PartyCandidateEcho]` is genuinely unsound
# (someone holding the base type could append a plain `CandidateEcho`). Parameterizing gives
# each subsystem a distinct concrete model — pydantic resolves the subscript to a real class,
# which is also what FastMCP needs to build a tool's output schema.
class AmbiguousResponse[EchoT: CandidateEcho](BaseModel):
    """Returned when a query matched several records and no single one could be chosen."""

    status: Literal["ambiguous"] = "ambiguous"
    query: str
    scope: str
    candidates: list[EchoT] = Field(default_factory=list)


class NotFoundResponse(BaseModel):
    """Returned when a query matched no records. `query` is the exact term searched for."""

    status: Literal["not_found"] = "not_found"
    query: str
    scope: str


class BatchUnresolvedEcho[EchoT: CandidateEcho](BaseModel):
    index: int
    query: str
    scope: str
    candidates: list[EchoT] = Field(default_factory=list)


class BatchResolvedEcho[ResolvedT](BaseModel):
    """One batch input that did resolve, kept so the model can continue with it."""

    index: int
    value: ResolvedT


class BatchAmbiguousResponse[EchoT: CandidateEcho, ResolvedT](BaseModel):
    """One combined payload for a batch where at least one input didn't resolve.

    `resolved` carries the inputs that did settle (policy step 3), so the model can keep those
    and ask once about the rest — dropping them would force re-resolution of work already done.
    """

    status: Literal["ambiguous"] = "ambiguous"
    unresolved: list[BatchUnresolvedEcho[EchoT]] = Field(default_factory=list)
    resolved: list[BatchResolvedEcho[ResolvedT]] = Field(default_factory=list)


type ToEcho[T, EchoT] = Callable[[Candidate[T]], EchoT]
type ToResolved[T, ResolvedT] = Callable[[T], ResolvedT]


def unresolved_response[T, EchoT: CandidateEcho](
    result: Unresolved[T],
    *,
    ambiguous_model: type[AmbiguousResponse[EchoT]],
    to_echo: ToEcho[T, EchoT],
) -> AmbiguousResponse[EchoT] | NotFoundResponse:
    """Convert a non-`Resolved` outcome into this subsystem's standard tool response.

    Callers short-circuit on this before doing any tool-specific fetch: there is nothing left
    to look up until the caller either picks a candidate or narrows the query.
    """
    if isinstance(result, NotFound):
        return NotFoundResponse(query=result.query, scope=result.scope)
    return ambiguous_model(
        query=result.query,
        scope=result.scope,
        candidates=[to_echo(candidate) for candidate in result.candidates],
    )


def batch_ambiguous_response[T, EchoT: CandidateEcho, ResolvedT](
    result: BatchAmbiguous[T],
    *,
    batch_model: type[BatchAmbiguousResponse[EchoT, ResolvedT]],
    unresolved_model: type[BatchUnresolvedEcho[EchoT]],
    resolved_model: type[BatchResolvedEcho[ResolvedT]],
    to_echo: ToEcho[T, EchoT],
    to_resolved: ToResolved[T, ResolvedT],
) -> BatchAmbiguousResponse[EchoT, ResolvedT]:
    """Convert a `BatchAmbiguous` into the wire payload, including already-resolved items."""
    return batch_model(
        unresolved=[
            unresolved_model(
                index=item.index,
                query=item.query,
                scope=item.scope,
                candidates=[to_echo(candidate) for candidate in item.candidates],
            )
            for item in result.unresolved
        ],
        resolved=[
            resolved_model(index=item.index, value=to_resolved(item.value))
            for item in result.resolved
        ],
    )
