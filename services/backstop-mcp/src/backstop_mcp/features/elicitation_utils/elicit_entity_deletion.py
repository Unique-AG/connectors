"""Ask the user to confirm a hard delete. The caller owns the prompt text."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from enum import StrEnum
from typing import Literal, cast

from fastmcp import Context
from fastmcp.server.elicitation import (
    AcceptedElicitation,
    handle_elicit_accept,
    parse_elicit_response_type,
)
from mcp.server.elicitation import CancelledElicitation
from mcp.types import ElicitRequest, ElicitRequestFormParams, ElicitResult, InputRequiredResult
from pydantic import BaseModel, Field

from backstop_mcp.dependencies import get_resolution_config
from backstop_mcp.features.resolution import (
    asks_as_tool_result,
    client_supports_elicitation,
    elicit_from_client,
)

logger = logging.getLogger(__name__)

type DeletionPromptCallback = Callable[[], Awaitable[str]]

REFUSE_BULK_DELETE = (
    'Refuse bulk wipes, "all test records", and any search-then-delete sweep. '
    + "Delete only one named record with a trusted id."
)

DELETION_NOT_CONFIRMED = (
    "Deletion was not confirmed. Nothing was deleted. Do not retry unless the user asks again."
)

DELETE = "Delete permanently"
KEEP = "Keep it"


class EntityDeletion(StrEnum):
    CONFIRMED = "CONFIRMED"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    DECLINED = "DECLINED"


class DeletionChoice(BaseModel):
    """Single-select dropdown; the safe option is preselected so Enter keeps the record."""

    choice: Literal["Keep it", "Delete permanently"] = Field(
        default=KEEP,
        title="Choice",
        description="Pick 'Delete permanently' to delete. This cannot be undone.",
    )


_ASK = "entity_deletion"


async def elicit_entity_deletion(
    ctx: Context,
    prompt: str | None = None,
    *,
    callback: DeletionPromptCallback | None = None,
    timeout_seconds: float | None = None,
) -> EntityDeletion | InputRequiredResult:
    """Prompt for a hard delete. The tool formats the message; this only classifies the answer.

    Pass either `prompt` or `callback`, not both. `callback` runs only after the client is
    known to support elicitation, so a tool can skip a preview fetch when the prompt will
    never be shown.

    Shows a dropdown with "Keep it" preselected, so accepting the form without touching it
    is a no-op rather than a delete.

    * `CONFIRMED` — the user accepted.
    * `NOT_AVAILABLE` — the client never advertised elicitation; the tool may proceed.
    * `DECLINED` — the user said no, cancelled, timed out, or the prompt failed. Do not delete.
    """
    assert (prompt is None) != (callback is None), "pass prompt or callback, not both"

    if timeout_seconds is None:
        timeout_seconds = get_resolution_config().elicit_timeout_seconds

    if not client_supports_elicitation(ctx):
        logger.info(
            "elicitation.entity_deletion.skipped",
            extra={"reason": "client lacks elicitation capability"},
        )
        return EntityDeletion.NOT_AVAILABLE

    if callback is not None:
        message = await callback()
    else:
        assert prompt is not None
        message = prompt

    config = parse_elicit_response_type(DeletionChoice)
    responses = getattr(ctx, "input_responses", None)
    answered: object = None
    if isinstance(responses, Mapping):
        answered = cast("Mapping[object, object]", responses).get(_ASK)
    if isinstance(answered, ElicitResult):
        if answered.action != "accept":
            logger.info(
                "elicitation.entity_deletion.dismissed",
                extra={"action": answered.action},
            )
            return EntityDeletion.DECLINED
        try:
            accepted = handle_elicit_accept(config, answered.content)
        except Exception as exc:
            logger.warning("elicitation.entity_deletion.degraded", extra={"error": str(exc)})
            return EntityDeletion.DECLINED
        data = cast("object", accepted.data)
        if isinstance(data, DeletionChoice) and data.choice == DELETE:
            return EntityDeletion.CONFIRMED
        logger.info("elicitation.entity_deletion.dismissed", extra={"action": "kept"})
        return EntityDeletion.DECLINED

    # 2026-07-28: picker is this tools/call result; client retries with input_responses.
    # Handshake: mid-call elicit (GET on /mcp) via elicit_from_client.
    if asks_as_tool_result(ctx):
        logger.info("elicitation.entity_deletion.input_required")
        return InputRequiredResult(
            input_requests={
                _ASK: ElicitRequest(
                    params=ElicitRequestFormParams(message=message, requested_schema=config.schema)
                )
            },
            request_state=_ASK,
        )

    try:
        async with asyncio.timeout(timeout_seconds):
            result = await elicit_from_client(ctx, message, DeletionChoice)
    except TimeoutError:
        logger.warning(
            "elicitation.entity_deletion.timed_out",
            extra={"timeout_seconds": timeout_seconds},
        )
        return EntityDeletion.DECLINED
    except Exception as exc:
        logger.warning("elicitation.entity_deletion.degraded", extra={"error": str(exc)})
        return EntityDeletion.DECLINED

    if isinstance(result, AcceptedElicitation) and result.data.choice == DELETE:
        return EntityDeletion.CONFIRMED
    if isinstance(result, AcceptedElicitation):
        logger.info("elicitation.entity_deletion.dismissed", extra={"action": "kept"})
        return EntityDeletion.DECLINED

    logger.info(
        "elicitation.entity_deletion.dismissed",
        extra={
            "action": "cancelled" if isinstance(result, CancelledElicitation) else "declined",
        },
    )
    return EntityDeletion.DECLINED
