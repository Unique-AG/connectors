"""Ask a person, on whichever MCP protocol era the client speaks.

Handshake era (up to 2025-11-25): the tool waits on `elicitation/create`, sent on the stream of
the open `tools/call`, for at most `timeout_before_cancel_seconds`.

2026-07-28: there is no back-channel. The first call returns an `InputRequiredResult`; the
client shows the form and calls the same tool again with the same arguments and the answer. The
tool runs from the top, and the same question finds its answer instead of asking.

The SDK seals `request_state` and binds it to the tool, its arguments and the signed-in user, so
an answer never counts for another call or another person. On top of that, each question carries
a nonce that the answering call deletes from the store, so an answer is used once even across
replicas, and a question is keyed by what the person saw, so an answer to an older version of it
does not count.
"""

import asyncio
import hashlib
import json
import logging
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field
from secrets import token_urlsafe
from typing import ClassVar
from typing import Literal
from typing import cast
from typing import overload

from fastmcp import Context
from key_value.aio.protocols import AsyncKeyValue
from mcp.server.request_state import RequestStateSecurity
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_REQUEST
from mcp.types import METHOD_NOT_FOUND
from mcp.types import ElicitRequest
from mcp.types import ElicitRequestFormParams
from mcp.types import ElicitResult
from mcp.types import InputRequiredResult
from mcp.types.version import MODERN_PROTOCOL_VERSIONS
from mcp_configs import ElicitationSettings
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import ValidationError

from mcp_elicitation.forms import ANSWER_FIELD
from mcp_elicitation.forms import CHOICE_FIELD
from mcp_elicitation.forms import CHOICES_FIELD
from mcp_elicitation.forms import CONFIRM
from mcp_elicitation.forms import Form
from mcp_elicitation.forms import choose_many_form
from mcp_elicitation.forms import choose_one_form
from mcp_elicitation.forms import confirm_form
from mcp_elicitation.protocol import confirmation_skipped
from mcp_elicitation.results import ChosenMany
from mcp_elicitation.results import ChosenOne
from mcp_elicitation.results import Confirmed
from mcp_elicitation.results import NeedsChoice
from mcp_elicitation.results import NotConfirmed
from mcp_elicitation.results import NotConfirmedError
from mcp_elicitation.results import Option

logger = logging.getLogger(__name__)

# The sealed state and the unused marker outlive the question, so an answer that arrives late is
# refused as expired rather than as unknown.
_GRACE_SECONDS = 60
_COLLECTION = "mcp-elicitation-questions"
_ROUND = "mcp_elicitation.round"
_ASK_AGAIN = (
    "Do not call this tool again for the same request unless the user asks for it in a new message."
)

type _Content = dict[str, str | int | float | bool | list[str] | None]
type _NoAnswerReason = Literal["unavailable", "timed_out", "no_answer"]


class _Answer(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    action: Literal["accept", "decline", "cancel"]
    content: _Content | None = None


class _NoAnswer(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    reason: _NoAnswerReason


class _State(BaseModel):
    """What one `InputRequiredResult` carries to the client and back, sealed by the SDK."""

    nonce: str
    asked: str
    answers: dict[str, _Answer]


@dataclass
class _Round:
    """What one `tools/call` knows: the answers given so far, and the question just answered."""

    answers: dict[str, _Answer] = field(default_factory=dict[str, _Answer])
    answered: str | None = None
    replayed: bool = False


def create_request_state_security(settings: ElicitationSettings) -> RequestStateSecurity:
    """Pass to `FastMCP(request_state_security=...)`.

    With `request_state_keys`, an answer opens on any replica and after a restart. Without them,
    only the process that asked can open it.
    """
    ttl = settings.timeout_before_cancel_seconds + _GRACE_SECONDS
    keys = [key.get_secret_value() for key in settings.request_state_keys]
    if keys:
        return RequestStateSecurity(keys=keys, ttl=ttl)
    return RequestStateSecurity.ephemeral(ttl=ttl)


class Elicitation:
    """Confirm an action or ask for a choice. Build one per app and share it.

    `store` keeps one marker per open question, so each answer is used once. A store every replica
    shares makes that hold across replicas; an in-memory store only within one process.
    """

    def __init__(self, settings: ElicitationSettings, store: AsyncKeyValue) -> None:
        self._timeout_seconds: float = settings.timeout_before_cancel_seconds
        self._marker_ttl_seconds: float = settings.timeout_before_cancel_seconds + _GRACE_SECONDS
        self._store: AsyncKeyValue = store

    @overload
    async def confirm(
        self,
        ctx: Context,
        message: str,
        *,
        agree: str,
        decline: str,
        nothing_happened: str,
        raises: Literal[True] = True,
    ) -> Confirmed | InputRequiredResult: ...

    @overload
    async def confirm(
        self,
        ctx: Context,
        message: str,
        *,
        agree: str,
        decline: str,
        nothing_happened: str,
        raises: Literal[False],
    ) -> Confirmed | NotConfirmed | InputRequiredResult: ...

    async def confirm(
        self,
        ctx: Context,
        message: str,
        *,
        agree: str,
        decline: str,
        nothing_happened: str,
        raises: bool = True,
    ) -> Confirmed | NotConfirmed | InputRequiredResult:
        """Ask the person to confirm `message`. Only an explicit `agree` confirms.

        `agree` and `decline` label the two answers. `nothing_happened` opens the message the
        model gets when the tool must not go ahead, such as "The rule was not deleted."
        With `raises`, that case raises `NotConfirmedError`; without, it returns `NotConfirmed`.
        """
        if confirmation_skipped(ctx):
            logger.info("Confirmation skipped: the client said no person has to confirm")
            return Confirmed(skipped=True)
        outcome = await self._ask(ctx, message, confirm_form(agree=agree, decline=decline))
        if isinstance(outcome, InputRequiredResult):
            return outcome
        if isinstance(outcome, _Answer) and _field(outcome, ANSWER_FIELD) == CONFIRM:
            logger.info("Confirmation given")
            return Confirmed(skipped=False)
        refusal = _refusal(outcome, nothing_happened)
        logger.info("Confirmation not given", extra={"reason": refusal.reason})
        if raises:
            raise NotConfirmedError(refusal)
        return refusal

    async def choose_one(
        self, ctx: Context, question: str, options: Sequence[Option]
    ) -> ChosenOne | NeedsChoice | InputRequiredResult:
        """Ask the person to pick one option. Its label should say what picking it does."""
        _check_options(options)
        if confirmation_skipped(ctx):
            return _needs_choice(question, options, multiple=False, reason="skipped")
        outcome = await self._ask(ctx, question, choose_one_form(options))
        if isinstance(outcome, InputRequiredResult):
            return outcome
        refs = {option.ref for option in options}
        picked = _field(outcome, CHOICE_FIELD) if isinstance(outcome, _Answer) else None
        if isinstance(picked, str) and picked in refs:
            return ChosenOne(ref=picked)
        return _needs_choice(question, options, multiple=False, reason=_why_unpicked(outcome))

    async def choose_many(
        self,
        ctx: Context,
        question: str,
        options: Sequence[Option],
        *,
        min_items: int = 1,
        max_items: int | None = None,
    ) -> ChosenMany | NeedsChoice | InputRequiredResult:
        """Ask the person to pick between `min_items` and `max_items` options."""
        _check_options(options)
        assert 1 <= min_items <= len(options), "min_items must be between 1 and the option count"
        assert max_items is None or min_items <= max_items, "max_items must not be below min_items"
        if confirmation_skipped(ctx):
            return _needs_choice(
                question,
                options,
                multiple=True,
                reason="skipped",
                min_items=min_items,
                max_items=max_items,
            )
        form = choose_many_form(options, min_items=min_items, max_items=max_items)
        outcome = await self._ask(ctx, question, form)
        if isinstance(outcome, InputRequiredResult):
            return outcome
        picked = _picked_many(outcome, options, min_items=min_items, max_items=max_items)
        if picked is not None:
            return ChosenMany(refs=picked)
        return _needs_choice(
            question,
            options,
            multiple=True,
            reason=_why_unpicked(outcome),
            min_items=min_items,
            max_items=max_items,
        )

    async def _ask(
        self, ctx: Context, message: str, form: Form
    ) -> _Answer | _NoAnswer | InputRequiredResult:
        key = _question_key(message, form)
        this_round = await self._round(ctx)
        if this_round.replayed:
            return _NoAnswer(reason="no_answer")
        known = this_round.answers.get(key)
        if known is not None:
            return known
        if not _can_elicit(ctx):
            logger.info("Not asked: the client cannot elicit")
            return _NoAnswer(reason="unavailable")
        if _modern(ctx) and this_round.answered != key:
            return await self._input_required(message, form, key=key, answers=this_round.answers)
        outcome = (
            _answer_from_responses(ctx, key)
            if _modern(ctx)
            else await self._elicit(ctx, message, form)
        )
        if isinstance(outcome, _Answer):
            this_round.answers[key] = outcome
        return outcome

    async def _round(self, ctx: Context) -> _Round:
        """What this call knows, read once per call however many questions the tool asks."""
        known = cast("object", await ctx.get_state(_ROUND))
        if isinstance(known, _Round):
            return known
        this_round = _Round()
        state = _state(ctx.request_state) if ctx.input_responses is not None else None
        if state is not None:
            if await self._store.delete(state.nonce, collection=_COLLECTION):
                this_round.answers = dict(state.answers)
                this_round.answered = state.asked
            else:
                logger.warning("Answer refused: already used or expired")
                this_round.replayed = True
        await ctx.set_state(_ROUND, this_round, serializable=False)
        return this_round

    async def _input_required(
        self, message: str, form: Form, *, key: str, answers: Mapping[str, _Answer]
    ) -> InputRequiredResult:
        nonce = token_urlsafe(32)
        await self._store.put(nonce, {}, collection=_COLLECTION, ttl=self._marker_ttl_seconds)
        state = _State(nonce=nonce, asked=key, answers=dict(answers))
        logger.info("Asked the client to show a form")
        return InputRequiredResult(
            input_requests={
                key: ElicitRequest(
                    params=ElicitRequestFormParams(message=message, requested_schema=form)
                )
            },
            request_state=state.model_dump_json(),
        )

    async def _elicit(self, ctx: Context, message: str, form: Form) -> _Answer | _NoAnswer:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                result = await ctx.session.elicit(
                    message=message, requested_schema=form, related_request_id=ctx.request_id
                )
        except TimeoutError:
            logger.warning("Not answered in time", extra={"timeout_seconds": self._timeout_seconds})
            return _NoAnswer(reason="timed_out")
        except MCPError as error:
            if error.error.code in (METHOD_NOT_FOUND, INVALID_REQUEST):
                logger.info("Not asked: the client refused to elicit", exc_info=error)
                return _NoAnswer(reason="unavailable")
            logger.warning("The client answered with an error", exc_info=error)
            return _NoAnswer(reason="no_answer")
        return _Answer(action=result.action, content=result.content)


def _question_key(message: str, form: Form) -> str:
    seen = json.dumps({"message": message, "form": form}, sort_keys=True)
    return hashlib.sha256(seen.encode()).hexdigest()[:32]


def _state(raw: str | None) -> _State | None:
    if raw is None:
        return None
    try:
        return _State.model_validate_json(raw)
    except ValidationError:
        logger.warning("Answer refused: request_state is not ours")
        return None


def _can_elicit(ctx: Context) -> bool:
    if ctx.request_context is None:
        return False
    capabilities = ctx.session.client_capabilities
    elicitation = capabilities.elicitation if capabilities is not None else None
    if elicitation is None:
        return False
    url_only = elicitation.form is None and elicitation.url is not None
    return not url_only


def _modern(ctx: Context) -> bool:
    request = ctx.request_context
    return request is not None and request.protocol_version in MODERN_PROTOCOL_VERSIONS


def _answer_from_responses(ctx: Context, key: str) -> _Answer | _NoAnswer:
    response = (ctx.input_responses or {}).get(key)
    if not isinstance(response, ElicitResult):
        logger.warning("Answer refused: the client sent no answer to the question")
        return _NoAnswer(reason="no_answer")
    return _Answer(action=response.action, content=response.content)


def _field(answer: _Answer, name: str) -> object:
    if answer.action != "accept" or answer.content is None:
        return None
    return answer.content.get(name)


def _picked_many(
    outcome: _Answer | _NoAnswer,
    options: Sequence[Option],
    *,
    min_items: int,
    max_items: int | None,
) -> tuple[str, ...] | None:
    if not isinstance(outcome, _Answer):
        return None
    picked = _field(outcome, CHOICES_FIELD)
    if not isinstance(picked, list):
        return None
    refs = {option.ref for option in options}
    chosen = tuple(cast("list[object]", picked))
    if not all(isinstance(ref, str) and ref in refs for ref in chosen):
        return None
    if len(set(chosen)) != len(chosen) or len(chosen) < min_items:
        return None
    if max_items is not None and len(chosen) > max_items:
        return None
    return cast("tuple[str, ...]", chosen)


def _check_options(options: Sequence[Option]) -> None:
    assert options, "a choice needs at least one option"
    assert len({option.ref for option in options}) == len(options), "option refs must be unique"


def _why_unpicked(
    outcome: _Answer | _NoAnswer,
) -> Literal["unavailable", "declined", "timed_out"]:
    if isinstance(outcome, _NoAnswer) and outcome.reason in ("unavailable", "timed_out"):
        return outcome.reason
    return "declined"


def _needs_choice(
    question: str,
    options: Sequence[Option],
    *,
    multiple: bool,
    reason: Literal["skipped", "unavailable", "declined", "timed_out"],
    min_items: int = 1,
    max_items: int | None = 1,
) -> NeedsChoice:
    logger.info("Choice left to the model", extra={"reason": reason})
    return NeedsChoice(
        question=question,
        options=tuple(options),
        multiple=multiple,
        min_items=min_items,
        max_items=max_items,
        reason=reason,
    )


def _refusal(outcome: _Answer | _NoAnswer, nothing_happened: str) -> NotConfirmed:
    if isinstance(outcome, _Answer):
        return NotConfirmed(
            reason="declined",
            message=(
                f"{nothing_happened} The person was asked to confirm this and did not agree. "
                "Nothing was changed, so this is not a failure to report as one: say that the "
                f"request was not confirmed. {_ASK_AGAIN}"
            ),
        )
    match outcome.reason:
        case "unavailable":
            return NotConfirmed(
                reason="unavailable",
                message=(
                    f"{nothing_happened} A person has to confirm this, and this client cannot ask "
                    "one. If you call this tool again, it will fail the same way. Tell the user "
                    f"that their client cannot ask them to confirm this request. {_ASK_AGAIN}"
                ),
            )
        case "timed_out":
            return NotConfirmed(
                reason="declined",
                message=(
                    f"{nothing_happened} The person was asked to confirm this and did not answer "
                    "in time. Tell the user, and that they can make the request again. "
                    f"{_ASK_AGAIN}"
                ),
            )
        case "no_answer":
            return NotConfirmed(
                reason="declined",
                message=(
                    f"{nothing_happened} The person was asked to confirm this, and no answer this "
                    "tool can use came back. Tell the user, and that they can make the request "
                    f"again. {_ASK_AGAIN}"
                ),
            )
