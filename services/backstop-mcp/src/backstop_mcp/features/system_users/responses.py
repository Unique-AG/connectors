"""Published system-user catalog response models."""

from typing import Literal

from pydantic import BaseModel, Field

from backstop_mcp.features.includes import InternalOwnerResponse

__all__ = ["ListSystemUsersResponse"]


class ListSystemUsersResponse(BaseModel):
    """Colleagues from the Backstop system-user catalog."""

    status: Literal["ok"] = Field(default="ok", description="Always 'ok'.")
    cache: Literal["ok", "stale"] = Field(
        description=(
            "'ok' when the catalog was fetched this call or is still fresh; 'stale' when a "
            "previous catalog is served because refresh failed."
        )
    )
    users: list[InternalOwnerResponse] = Field(
        description=(
            "Our colleagues, in catalog order. Echo `user_name` into search_opportunities "
            "`representative` — that filter takes a login, not a display name. `disabled` is "
            "true for a departed colleague; do not treat their empty pipeline as 'no coverage'."
        )
    )
