"""Ask the user to confirm a hard delete. The caller owns the prompt text."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Literal

from fastmcp import Context
from fastmcp.server.elicitation import AcceptedElicitation
from mcp.server.elicitation import CancelledElicitation
from pydantic import BaseModel, Field

from backstop_mcp.dependencies import get_resolution_config
from backstop_mcp.features.resolution import client_supports_elicitation

logger = logging.getLogger(__name__)

type DeletionPromptCallback = Callable[[], Awaitable[str]]


class EntityDeletion(StrEnum):
    CONFIRMED = "CONFIRMED"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    DECLINED = "DECLINED"


DELETE = "Delete permanently"
KEEP = "Keep it"


class DeletionChoice(BaseModel):
    """Single-select dropdown; the safe option is preselected so Enter keeps the record."""

    choice: Literal["Keep it", "Delete permanently"] = Field(
        default=KEEP,
        title="Choice",
        description="Pick 'Delete permanently' to delete. This cannot be undone.",
    )


async def elicit_entity_deletion(
    ctx: Context,
    prompt: str | None = None,
    *,
    callback: DeletionPromptCallback | None = None,
    timeout_seconds: float | None = None,
) -> EntityDeletion:
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

    try:
        async with asyncio.timeout(timeout_seconds):
            result = await ctx.elicit(message=message, response_type=DeletionChoice)
    except TimeoutError:
        logger.warning(
            "elicitation.entity_deletion.timed_out",
            extra={"timeout_seconds": timeout_seconds},
        )
        return EntityDeletion.DECLINED
    except Exception as exc:
        logger.warning("elicitation.entity_deletion.degraded", extra={"error": str(exc)})
        return EntityDeletion.DECLINED

    if isinstance(result, AcceptedElicitation):
        if result.data.choice == DELETE:
            return EntityDeletion.CONFIRMED
        logger.info("elicitation.entity_deletion.dismissed", extra={"action": "kept"})
        return EntityDeletion.DECLINED

    logger.info(
        "elicitation.entity_deletion.dismissed",
        extra={
            "action": "cancelled" if isinstance(result, CancelledElicitation) else "declined",
        },
    )
    return EntityDeletion.DECLINED
