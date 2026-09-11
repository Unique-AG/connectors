"""Ask the user to confirm a hard delete. The caller owns the prompt text."""

import asyncio
import logging
from enum import StrEnum

from fastmcp import Context
from fastmcp.server.elicitation import AcceptedElicitation
from mcp.server.elicitation import CancelledElicitation, DeclinedElicitation

from backstop_mcp.dependencies import get_resolution_config
from backstop_mcp.features.resolution import client_supports_elicitation

logger = logging.getLogger(__name__)

DELETE_PERMANENTLY = "Delete permanently"
KEEP_THIS_RECORD = "Keep this record"


class EntityDeletion(StrEnum):
    CONFIRMED = "CONFIRMED"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    DECLINED = "DECLINED"


async def elicit_entity_deletion(
    ctx: Context,
    prompt: str,
    *,
    timeout_seconds: float | None = None,
) -> EntityDeletion:
    """Prompt for a hard delete. The tool formats `prompt`; this only classifies the answer.

    * `CONFIRMED` — the user picked delete.
    * `NOT_AVAILABLE` — the client never advertised elicitation; the tool may proceed.
    * `DECLINED` — the user said no, cancelled, timed out, or the prompt failed. Do not delete.
    """
    if timeout_seconds is None:
        timeout_seconds = get_resolution_config().elicit_timeout_seconds

    if not client_supports_elicitation(ctx):
        logger.info(
            "elicitation.entity_deletion.skipped",
            extra={"reason": "client lacks elicitation capability"},
        )
        return EntityDeletion.NOT_AVAILABLE

    try:
        async with asyncio.timeout(timeout_seconds):
            result = await ctx.elicit(
                message=prompt, response_type=[DELETE_PERMANENTLY, KEEP_THIS_RECORD]
            )
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
        if result.data == DELETE_PERMANENTLY:
            return EntityDeletion.CONFIRMED
        logger.info("elicitation.entity_deletion.dismissed", extra={"action": "declined"})
        return EntityDeletion.DECLINED

    assert isinstance(result, (DeclinedElicitation, CancelledElicitation))
    logger.info(
        "elicitation.entity_deletion.dismissed",
        extra={
            "action": "declined" if isinstance(result, DeclinedElicitation) else "cancelled",
        },
    )
    return EntityDeletion.DECLINED
