"""Ask the user to confirm a hard delete. The caller owns the prompt text."""

import logging
from collections.abc import Awaitable, Callable, Mapping
from enum import StrEnum
from typing import Literal, cast

from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.server.elicitation import handle_elicit_accept, parse_elicit_response_type
from mcp.types import (
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
)
from pydantic import BaseModel, Field

from backstop_mcp.features.resolution import (
    client_supports_elicitation,
    client_supports_input_required,
    negotiated_protocol_version,
)
from backstop_mcp.models import OmitNoneModel

logger = logging.getLogger(__name__)

type DeletionPromptCallback = Callable[[], Awaitable[str]]

DELETION_INPUT_KEY = "entity_deletion"

CONFIRM_FIELD_DESCRIPTION = (
    "Set true only after the user agreed in chat to delete this record. Required when "
    "the tool returned `status=needs_confirmation` because this client cannot show the "
    "delete form (MCP older than 2026-07-28). Do not set true on the first call."
)

DELETION_NOT_CONFIRMED = (
    "Deletion was not confirmed. Nothing was deleted. Do not retry unless the user asks again."
)

CONFIRM_RETRY_MESSAGE = (
    "This client cannot show the delete confirmation form (MCP older than 2026-07-28). "
    "Show the preview to the user. If they agree, retry the same tool with confirm=true. "
    "Do not invent an id. Nothing was deleted."
)

DELETE = "Delete permanently"
KEEP = "Keep it"


class EntityDeletion(StrEnum):
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"


class DeletionChoice(BaseModel):
    """Single-select dropdown; the safe option is preselected so Enter keeps the record."""

    choice: Literal["Keep it", "Delete permanently"] = Field(
        default=KEEP,
        title="Choice",
        description="Pick 'Delete permanently' to delete. This cannot be undone.",
    )


class DeletionNeedsConfirmationResponse(OmitNoneModel):
    """Returned when a hard delete needs a chat confirm because the form cannot paint."""

    status: Literal["needs_confirmation"] = Field(
        default="needs_confirmation",
        description=(
            "Always 'needs_confirmation': nothing was deleted. Show `preview` to the "
            "user and retry with `confirm=true` if they agree."
        ),
    )
    message: str = Field(
        default=CONFIRM_RETRY_MESSAGE,
        description="What the model should tell the user, including how to retry.",
    )
    preview: str = Field(
        description="The delete confirmation text the form would have shown."
    )


type DeletionElicitResult = InputRequiredResult | DeletionNeedsConfirmationResponse

_DELETION_ELICIT = parse_elicit_response_type(DeletionChoice)


async def elicit_entity_deletion(
    ctx: Context,
    prompt: str | None = None,
    *,
    callback: DeletionPromptCallback | None = None,
) -> DeletionElicitResult | None:
    """Prompt for a hard delete and return what the tool should return, or `None` to delete.

    Pass either `prompt` or `callback`, not both. `callback` runs only after a confirm
    will actually be shown — a 2026-07-28 form, or a handshake-era `needs_confirmation`
    preview — so a tool can skip a preview fetch when the prompt will never be shown.

    Shows a dropdown with "Keep it" preselected, so accepting the form without touching it
    is a no-op rather than a delete.

    Never calls `ctx.elicit`. Cursor advertises elicitation but does not paint a pushed
    form, so a wait hangs the tool.

    * `None` — proceed with the delete (no elicitation capability, or the user confirmed).
    * `InputRequiredResult` — return unchanged so a 2026-07-28 client can paint the form.
    * `DeletionNeedsConfirmationResponse` — handshake-era client; the model asks in chat
      and retries with `confirm=true`.
    * Raises `ToolError` when the user declined or cancelled.
    """
    assert (prompt is None) != (callback is None), "pass prompt or callback, not both"

    if not client_supports_elicitation(ctx):
        logger.info(
            "elicitation.entity_deletion.skipped",
            extra={"reason": "client lacks elicitation capability"},
        )
        return None

    prior = _deletion_response(ctx)
    if prior is not None:
        classified = _classify_elicit_result(prior)
        if classified is EntityDeletion.DECLINED:
            raise ToolError(DELETION_NOT_CONFIRMED)
        return None

    if callback is not None:
        message = await callback()
    else:
        assert prompt is not None
        message = prompt

    if not client_supports_input_required(ctx):
        logger.info(
            "elicitation.entity_deletion.needs_confirmation",
            extra={"protocol_version": negotiated_protocol_version(ctx)},
        )
        return DeletionNeedsConfirmationResponse(preview=message)

    logger.info("elicitation.entity_deletion.ask")
    return InputRequiredResult(
        input_requests={
            DELETION_INPUT_KEY: ElicitRequest(
                params=ElicitRequestFormParams(
                    message=message,
                    requested_schema=_DELETION_ELICIT.schema,
                )
            )
        }
    )


def _deletion_response(ctx: Context) -> ElicitResult | None:
    responses = cast("object | None", getattr(ctx, "input_responses", None))
    if not isinstance(responses, Mapping):
        return None
    typed_responses = cast("Mapping[str, object]", responses)
    answer = typed_responses.get(DELETION_INPUT_KEY)
    return answer if isinstance(answer, ElicitResult) else None


def _classify_elicit_result(result: ElicitResult) -> EntityDeletion:
    if result.action != "accept":
        logger.info(
            "elicitation.entity_deletion.dismissed",
            extra={"action": "cancelled" if result.action == "cancel" else "declined"},
        )
        return EntityDeletion.DECLINED
    try:
        accepted = handle_elicit_accept(_DELETION_ELICIT, result.content)
    except Exception as exc:
        logger.warning("elicitation.entity_deletion.degraded", extra={"error": str(exc)})
        return EntityDeletion.DECLINED
    data = cast("object", accepted.data)
    if not isinstance(data, DeletionChoice):
        return EntityDeletion.DECLINED
    return _classify_choice(data.choice)


def _classify_choice(choice: str) -> EntityDeletion:
    if choice == DELETE:
        return EntityDeletion.CONFIRMED
    logger.info("elicitation.entity_deletion.dismissed", extra={"action": "kept"})
    return EntityDeletion.DECLINED
