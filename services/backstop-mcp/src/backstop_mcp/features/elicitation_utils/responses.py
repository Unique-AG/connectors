"""Published delete-elicitation responses.

Handshake-era clients cannot paint the confirm form, so the tool returns this
and the model asks in chat, then retries with `confirm=true`.
"""

from typing import Literal

from pydantic import Field

from backstop_mcp.models import OmitNoneModel

CONFIRM_RETRY_MESSAGE = (
    "This client cannot show the delete confirmation form (MCP older than 2026-07-28). "
    "Show the preview to the user. If they agree, retry the same tool with confirm=true. "
    "Do not invent an id. Nothing was deleted."
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
    preview: str = Field(description="The delete confirmation text the form would have shown.")
