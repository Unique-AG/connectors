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
4. Client can't elicit, declines, cancels, or doesn't answer before
   `RESOLUTION_ELICIT_TIMEOUT_SECONDS` → degrade from (2) to the same structured
   payload as (3).
5. Zero matches → `NotFound`, naming the query that was actually used.
"""

import asyncio
import json
import logging
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from typing import Annotated, Any, ClassVar, Literal, Protocol, TypeIs, cast, overload

import fastmcp
from fastmcp import Context
from fastmcp.server.dependencies import get_http_request
from fastmcp.server.elicitation import (
    AcceptedElicitation,
    handle_elicit_accept,
    parse_elicit_response_type,
)
from mcp.server.elicitation import CancelledElicitation, DeclinedElicitation
from mcp.types import (
    ClientCapabilities,
    ElicitationCapability,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
)
from mcp.types.version import MODERN_PROTOCOL_VERSIONS
from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.dependencies import get_resolution_config

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
# Handshake (2025-11-25): mid-call `elicitation/create`. On Streamable HTTP the form
# must ride GET, not the open tools/call POST — see `elicit_from_client`.
# Modern (2026-07-28): no back-channel. Return `InputRequiredResult`; the client
# shows the form and retries `tools/call` with `input_responses`.


class _ClientCapabilityChecker(Protocol):
    def check_client_capability(self, capability: ClientCapabilities) -> bool: ...


class _RequestContext(Protocol):
    @property
    def session(self) -> _ClientCapabilityChecker: ...


def input_required(outcome: object) -> TypeIs[InputRequiredResult]:
    """True when the tool must return now so a 2026-07-28 client can show the form."""
    return isinstance(outcome, InputRequiredResult)


def asks_as_tool_result(ctx: Context) -> bool:
    """True on 2026-07-28: no elicit back-channel, so return `InputRequiredResult`.

    The client shows that form and calls the same tool again with `input_responses`.
    Handshake stays on `elicit_from_client` instead.
    """
    request = getattr(ctx, "request_context", None)
    version = getattr(request, "protocol_version", None)
    return version in MODERN_PROTOCOL_VERSIONS


def _on_streamable_http() -> bool:
    """True for the `/mcp` POST that owns the open `tools/call`.

    Handshake `elicitation/create` must not ride that POST (see `elicit_from_client`).
    """
    try:
        path = get_http_request().url.path.rstrip("/")
    except Exception:
        return False
    return path == fastmcp.settings.streamable_http_path.rstrip("/")


@overload
async def elicit_from_client[T](
    ctx: Context, message: str, response_type: type[T]
) -> AcceptedElicitation[T] | DeclinedElicitation | CancelledElicitation: ...


@overload
async def elicit_from_client(
    ctx: Context, message: str, response_type: list[str]
) -> AcceptedElicitation[str] | DeclinedElicitation | CancelledElicitation: ...


async def elicit_from_client[T](
    ctx: Context,
    message: str,
    response_type: type[T] | list[str],
) -> AcceptedElicitation[T] | AcceptedElicitation[str] | DeclinedElicitation | CancelledElicitation:
    """Handshake mid-call elicit. On Streamable HTTP, send it on GET, not the open POST.

    Handshake (`2025-11-25`) still uses `elicitation/create`. The bug was which HTTP
    stream that request rode. `ctx.elicit()` always sets `related_request_id` to the
    current `tools/call`. On Streamable HTTP (`/mcp`) that puts the form on the open
    POST SSE. Inspector and Cursor wait for that POST to finish before they render
    anything on it, so the picker only appeared after the 45s timeout — then as a
    cancelled form.

    Classic SSE never had this problem: its GET stays live, so a mid-call elicit is
    visible immediately. We do not mount SSE; `/mcp` is the only transport.

    On `/mcp` this does not call `ctx.elicit()`. It calls `session.elicit_form`
    with no `related_request_id`. FastMCP then sends `elicitation/create` on the
    standalone GET stream. The POST stays open waiting for the answer; the form
    can show while the tool is still running. Tests and non-`/mcp` requests keep
    `ctx.elicit()`.
    """
    if not _on_streamable_http():
        return await ctx.elicit(message=message, response_type=response_type)

    logger.info("resolution.elicit.standalone_stream")
    config = parse_elicit_response_type(response_type)
    # No related_request_id → Streamable HTTP GET stream, not the tools/call POST.
    raw = await ctx.session.elicit_form(message, config.schema)
    if raw.action == "accept":
        return handle_elicit_accept(config, raw.content)
    if raw.action == "decline":
        return DeclinedElicitation()
    return CancelledElicitation()


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


_ASK = "resolve"
_CHOSEN_ATTR = "_resolution_chosen"


def _ask_key[T](ambiguous: Ambiguous[T]) -> str:
    return f"{_ASK}:{ambiguous.scope}:{ambiguous.query}"


def _remember[T](ctx: Context, key: str, candidate_key: str) -> None:
    remembered = getattr(ctx, _CHOSEN_ATTR, None)
    if not isinstance(remembered, dict):
        remembered = {}
        setattr(ctx, _CHOSEN_ATTR, remembered)
    remembered[key] = candidate_key


def _str_map(raw: object) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        return {}
    recalled: dict[str, str] = {}
    for key, value in cast("Mapping[object, object]", raw).items():
        if isinstance(key, str) and isinstance(value, str):
            recalled[key] = value
    return recalled


def _remembered(ctx: Context) -> dict[str, str]:
    return _str_map(getattr(ctx, _CHOSEN_ATTR, None))


def _state_chosen(ctx: Context) -> dict[str, str]:
    raw = getattr(ctx, "request_state", None)
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        parsed = cast("object", json.loads(raw))
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, Mapping):
        return {}
    return _str_map(cast("Mapping[object, object]", parsed).get("chosen"))


def _resolved_by_key[T](ambiguous: Ambiguous[T], candidate_key: str) -> Resolution[T]:
    for candidate in ambiguous.candidates:
        if candidate.key == candidate_key:
            return Resolved(value=candidate.value)
    return ambiguous


def _apply_elicit_result[T](
    ambiguous: Ambiguous[T],
    by_label: dict[str, Candidate[T]],
    result: AcceptedElicitation[str] | DeclinedElicitation | CancelledElicitation,
    outcome_log: dict[str, object],
) -> Resolution[T]:
    if isinstance(result, AcceptedElicitation):
        chosen = by_label.get(result.data)
        if chosen is None:
            logger.warning("resolution.elicit.unknown_choice", extra=outcome_log)
            return ambiguous
        return Resolved(value=chosen.value)
    assert isinstance(result, (DeclinedElicitation, CancelledElicitation))
    logger.info(
        "resolution.elicit.dismissed",
        extra={
            **outcome_log,
            "action": "declined" if isinstance(result, DeclinedElicitation) else "cancelled",
        },
    )
    return ambiguous


async def elicit_choice[T](
    ctx: Context,
    ambiguous: Ambiguous[T],
    *,
    prompt: str,
    timeout_seconds: float | None = None,
) -> Resolution[T] | InputRequiredResult:
    """Ask the user to pick one candidate, degrading to `ambiguous` if that isn't possible.

    Returns the original `Ambiguous` unchanged whenever a user-visible choice can't be
    obtained — unsupported client, declined, cancelled, timed out, or any transport failure —
    so the caller's single "not resolved" branch covers every degradation path.

    `timeout_seconds` defaults to `RESOLUTION_ELICIT_TIMEOUT_SECONDS`; see `ResolutionConfig`
    for why a deadline is needed at all. Read through the cached provider rather than
    constructed here, so every resolver in a process shares the one value `create_app` was
    given.

    Every one of those paths is logged. An unanswered prompt is otherwise indistinguishable
    from a slow upstream: the tool reports success either way, because returning the candidate
    list *is* the documented outcome, so duration is the only clue anything went wrong.
    """
    assert len(ambiguous.candidates) >= 2, "elicit_choice requires at least two candidates"

    if timeout_seconds is None:
        timeout_seconds = get_resolution_config().elicit_timeout_seconds

    outcome_log: dict[str, object] = {
        "query": ambiguous.query,
        "scope": ambiguous.scope,
        "candidates": len(ambiguous.candidates),
    }
    key = _ask_key(ambiguous)
    prior = {**_state_chosen(ctx), **_remembered(ctx)}
    if key in prior:
        return _resolved_by_key(ambiguous, prior[key])

    if not client_supports_elicitation(ctx):
        logger.info(
            "resolution.elicit.skipped",
            extra={**outcome_log, "reason": "client lacks elicitation capability"},
        )
        return ambiguous

    by_label = _unique_labels(ambiguous.candidates)
    config = parse_elicit_response_type(list(by_label))
    responses = getattr(ctx, "input_responses", None)
    answered: object = None
    if isinstance(responses, Mapping):
        answered = cast("Mapping[object, object]", responses).get(key)
    if isinstance(answered, ElicitResult):
        if answered.action != "accept":
            logger.info(
                "resolution.elicit.dismissed",
                extra={**outcome_log, "action": answered.action},
            )
            return ambiguous
        try:
            accepted = handle_elicit_accept(config, answered.content)
        except Exception as exc:
            logger.warning("resolution.elicit.degraded", extra={**outcome_log, "error": str(exc)})
            return ambiguous
        chosen = by_label.get(cast("str", accepted.data))
        if chosen is None:
            logger.warning("resolution.elicit.unknown_choice", extra=outcome_log)
            return ambiguous
        _remember(ctx, key, chosen.key)
        return Resolved(value=chosen.value)

    # 2026-07-28: picker is this tools/call result; client retries with input_responses.
    # Handshake: mid-call elicit (GET on /mcp) via elicit_from_client.
    if asks_as_tool_result(ctx):
        logger.info("resolution.elicit.input_required", extra=outcome_log)
        return InputRequiredResult(
            input_requests={
                key: ElicitRequest(
                    params=ElicitRequestFormParams(message=prompt, requested_schema=config.schema)
                )
            },
            request_state=json.dumps({"chosen": prior}),
        )

    try:
        # Only this deadline is swallowed. A `CancelledError` from the caller's own scope is a
        # `BaseException`, so it keeps propagating and the tool still aborts when the client
        # gives up on the whole call.
        async with asyncio.timeout(timeout_seconds):
            result = await elicit_from_client(ctx, prompt, list(by_label))
    except TimeoutError:
        logger.warning(
            "resolution.elicit.timed_out",
            extra={**outcome_log, "timeout_seconds": timeout_seconds},
        )
        return ambiguous
    except Exception as exc:
        logger.warning("resolution.elicit.degraded", extra={**outcome_log, "error": str(exc)})
        return ambiguous

    return _apply_elicit_result(ambiguous, by_label, result, outcome_log)


async def elicit_if_ambiguous[T](
    ctx: Context, outcome: Resolution[T]
) -> Resolution[T] | InputRequiredResult:
    """Policy step 2: several matches on a single call → ask; otherwise leave the outcome."""
    if not isinstance(outcome, Ambiguous):
        return outcome
    return await elicit_choice(
        ctx,
        outcome,
        prompt=f'Multiple {outcome.scope} matched "{outcome.query}". Which one did you mean?',
    )


# --- LLM-facing response models -------------------------------------------------------------


class CandidateResponse(BaseModel):
    """Base shape every candidate response shares. Subsystems subclass to add their fields."""

    key: str = Field(
        description=(
            "Stable identity for this candidate. Echo it only as part of picking this option "
            "— it is not a Backstop record id."
        )
    )
    label: str = Field(description="What to show the user when asking which record they meant.")


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
            "Collection the query was resolved against, e.g. 'organizations', 'people', "
            "or 'products'."
        )
    )
    candidates: list[CandidateT] = Field(
        default_factory=list,
        description=(
            "The matching records. Show `label` to the user, then retry with that candidate's "
            "`id` (and `search_type` when the candidate has one) — never invent an id."
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
            "Collection the query was resolved against, e.g. 'organizations', 'people', "
            "or 'products'."
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


def unresolved_response[T, CandidateT: CandidateResponse, AmbiguousT: AmbiguousResponse[Any]](
    result: Unresolved[T],
    *,
    ambiguous_model: type[AmbiguousT],
    to_candidate: ToCandidateResponse[T, CandidateT],
) -> AmbiguousT | NotFoundResponse:
    """Convert a non-`Resolved` outcome into this subsystem's standard tool response.

    Callers short-circuit on this before doing any tool-specific fetch: there is nothing left
    to look up until the caller either picks a candidate or narrows the query.

    Generic over the ambiguous model itself, not just its candidate type, so a subsystem that
    subclasses `AmbiguousResponse` to reword its schema (`ProductAmbiguousResponse`) gets that
    subclass back rather than the base.
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
