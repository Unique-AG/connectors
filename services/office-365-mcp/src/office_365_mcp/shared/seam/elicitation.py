import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import cast

from fastmcp import Context
from fastmcp.server.elicitation import (
    AcceptedElicitation,
    handle_elicit_accept,
    parse_elicit_response_type,
)
from mcp.shared.exceptions import MCPError
from mcp.types import (
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
)
from mcp.types.version import MODERN_PROTOCOL_VERSIONS
from pydantic import BaseModel

_ASK_AGAIN = (
    "Do not call this tool again for the same request unless the user asks for it in a new message."
)

type Confirmed = str | InputRequiredResult | None

type Confirm = Callable[[str, str], Awaitable[Confirmed]]

type DigestPart = str | int | bool | None | Sequence[DigestPart] | Mapping[str, DigestPart]

_CONFIRMATION = "confirm"


def _canonical(part: DigestPart) -> object:
    if isinstance(part, str | int | bool | None):
        return part
    if isinstance(part, Mapping):
        return {key: _canonical(value) for key, value in part.items()}
    return [_canonical(value) for value in part]


def confirmation_digest(*parts: BaseModel | DigestPart) -> str:
    canonical = [
        part.model_dump(mode="json", exclude_none=True)
        if isinstance(part, BaseModel)
        else _canonical(part)
        for part in parts
    ]
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()


def _modern_protocol(ctx: Context) -> bool:
    request = ctx.request_context
    return request is not None and request.protocol_version in MODERN_PROTOCOL_VERSIONS


_CANNOT_BE_ASKED = frozenset({METHOD_NOT_FOUND, INVALID_REQUEST})


def _nobody_to_ask(nothing_happened: str) -> str:
    return (
        f"{nothing_happened} This connector must ask a person to agree to this request. The MCP "
        + "client or its connection does not support elicitation, so this connector cannot ask a "
        + "person. If you call this tool again, the call will fail the same way.\n\n"
        + "Tell the user that their client cannot ask them to agree to this request. Tell them "
        + "that they can do this task in the Microsoft 365 app. "
        + _ASK_AGAIN
    )


def _no_answer(nothing_happened: str) -> str:
    return (
        f"{nothing_happened} This connector tried to ask a person to agree to this request. "
        + "The MCP client sent no answer that this connector can use. Tell the user that this "
        + "connector received no answer, and that they can make the same request again. "
        + _ASK_AGAIN
    )


def _not_agreed(nothing_happened: str) -> str:
    return (
        f"{nothing_happened} The person at the other end of this conversation was asked to "
        + "confirm it and did not agree. Nothing was changed, so this is not a failure to "
        + f"report as one: say that the request was not confirmed. {_ASK_AGAIN}"
    )


def _another_request(nothing_happened: str) -> str:
    return (
        f"{nothing_happened} The confirmation that came back was given for a different request "
        + "than this one, so that agreement does not cover this request, and nothing was changed. "
        + f"Ask the user again and call this tool with exactly what they confirm. {_ASK_AGAIN}"
    )


def person_confirms(ctx: Context, *, agree: str, decline: str, nothing_happened: str) -> Confirm:
    answers = parse_elicit_response_type([agree, decline])

    async def elicited(question: str) -> str | None:
        try:
            answer = await ctx.elicit(question, response_type=[agree, decline])
        except Exception as unanswered:
            if isinstance(unanswered, MCPError) and unanswered.code in _CANNOT_BE_ASKED:
                return _nobody_to_ask(nothing_happened)
            return _no_answer(nothing_happened)
        if not isinstance(answer, AcceptedElicitation) or answer.data != agree:
            return _not_agreed(nothing_happened)
        return None

    def asked(question: str, about: str) -> Confirmed:
        answered = (ctx.input_responses or {}).get(_CONFIRMATION)
        if answered is None:
            return InputRequiredResult(
                input_requests={
                    _CONFIRMATION: ElicitRequest(
                        params=ElicitRequestFormParams(
                            message=question, requested_schema=answers.schema
                        )
                    )
                },
                request_state=about,
            )
        if not isinstance(answered, ElicitResult) or answered.action != "accept":
            return _not_agreed(nothing_happened)
        if ctx.request_state != about:
            return _another_request(nothing_happened)
        try:
            accepted = handle_elicit_accept(answers, answered.content)
        except Exception:
            return _no_answer(nothing_happened)
        chosen = cast("str", accepted.data)
        return None if chosen == agree else _not_agreed(nothing_happened)

    async def confirm(question: str, about: str) -> Confirmed:
        return asked(question, about) if _modern_protocol(ctx) else await elicited(question)

    return confirm


def answer_pending(ctx: Context) -> bool:
    return (ctx.input_responses or {}).get(_CONFIRMATION) is not None
