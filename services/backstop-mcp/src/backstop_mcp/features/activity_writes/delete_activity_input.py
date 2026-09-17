"""`delete_activity` input: `kind` plus the activity id. Delete is permanent."""

from typing import Literal

from pydantic import BaseModel, Field

from backstop_mcp.features.elicitation_utils import REFUSE_BULK_DELETE
from backstop_mcp.models import NonEmptyStr

__all__ = [
    "DELETE_ACTIVITY_INPUT_DESCRIPTION",
    "DeleteActivityInput",
]

DELETE_ACTIVITY_INPUT_DESCRIPTION = (
    "Required. The activity to hard-delete. Needs `kind` and `activity_id` (create echo, "
    + "search row, or history handle). Never invent an id. Deletion is permanent: Backstop "
    + "has no recycle bin. The tool reads the record and asks the user to confirm when "
    + "the client can elicit; otherwise it deletes immediately. "
    + REFUSE_BULK_DELETE
)


class DeleteActivityInput(BaseModel):
    """Hard-delete a note, meeting, call, task, email, or document."""

    kind: Literal["note", "meeting", "call", "task", "email", "document"] = Field(
        description=(
            "Which collection the record lives in. `meeting` and `call` share `meeting-or-calls`."
        )
    )
    activity_id: NonEmptyStr = Field(
        description=(
            "Required. Backstop id from a create echo, a `search_activities` row, or a "
            "`get_activity_history` handle (`notes_123`, `meeting-or-calls_123`). Never "
            "invent or guess."
        )
    )
