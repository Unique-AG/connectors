import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast

from fastmcp.exceptions import ToolError
from kiota_abstractions.headers_collection import HeadersCollection
from kiota_abstractions.serialization import AdditionalDataHolder, Parsable
from kiota_serialization_json.json_serialization_writer import JsonSerializationWriter
from mcp.types import InputRequiredResult
from pydantic import BaseModel

from office_365_mcp.graph_client import GraphFailure, not_graph
from office_365_mcp.shared.seam.elicitation import Confirm, confirmation_digest

_ETAG = "@odata.etag"

_CHANGED_SINCE_READ = 412


@dataclass(frozen=True, slots=True)
class Refusal:
    reason: str


@dataclass(frozen=True, slots=True)
class Question:
    text: str
    shown: tuple[Parsable, ...]
    guarded: Parsable | None = None


type Prepare = Callable[[bool], Awaitable[Question | Refusal | None]]

type Write[T] = Callable[[HeadersCollection], Awaitable[T | Refusal]]


@dataclass(frozen=True, slots=True)
class Approval:
    tool: str
    uri: str
    change: BaseModel
    confirm: Confirm
    answer_pending: bool
    nothing_happened: str


def _etag(entity: Parsable | None) -> str | None:
    if not isinstance(entity, AdditionalDataHolder):
        return None
    etag = entity.additional_data.get(_ETAG)
    return etag if isinstance(etag, str) and etag else None


def _bound(entity: Parsable) -> str:
    etag = _etag(entity)
    if etag is not None:
        return etag
    writer = JsonSerializationWriter()
    writer.write_object_value(None, entity)
    content = cast("object", json.loads(writer.get_serialized_content()))
    return json.dumps(content, sort_keys=True)


def _digest(approval: Approval, question: Question) -> str:
    return confirmation_digest(
        approval.tool,
        approval.uri,
        approval.change,
        question.text,
        [_bound(entity) for entity in question.shown],
    )


def _changed_meanwhile(nothing_happened: str) -> str:
    return (
        "The item changed while the user decided, for example because another person changed "
        + f"it. {nothing_happened} Read the item again, and then ask the user again."
    )


async def approved_write[T](
    approval: Approval, *, prepare: Prepare, write: Write[T]
) -> T | InputRequiredResult | Refusal:
    question = await prepare(approval.answer_pending)
    if isinstance(question, Refusal):
        return question
    headers = HeadersCollection()
    if question is not None:
        about = _digest(approval, question)
        with not_graph():
            answer = await approval.confirm(question.text, about)
        if isinstance(answer, InputRequiredResult):
            return answer
        if answer is not None:
            return Refusal(answer)
        if not approval.answer_pending:
            again = await prepare(True)
            if isinstance(again, Refusal):
                return again
            if again is None or _digest(approval, again) != about:
                return Refusal(_changed_meanwhile(approval.nothing_happened))
        etag = _etag(question.guarded)
        if etag is not None:
            headers.add("If-Match", etag)
    try:
        return await write(headers)
    except GraphFailure as failure:
        if failure.status != _CHANGED_SINCE_READ or not headers.contains("If-Match"):
            raise
        return Refusal(_changed_meanwhile(approval.nothing_happened))


def answered[T](result: T | Refusal) -> T:
    if isinstance(result, Refusal):
        raise ToolError(result.reason)
    return result
