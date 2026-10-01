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
    "Required. The activity to hard-delete. Needs `kind` and `activity_id`. Note, meeting, "
    + "call, and document ids come from a create echo, a search row, or a history handle. "
    + "Email ids come from `attach_file` or a history email `activity_id`. Task ids come "
    + "from the create echo or `get_tasks_for_party`. Never invent an id. Deletion is "
    + "permanent: Backstop "
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
            "Required. For a note, meeting, call, or document: a create echo, a "
            "`search_activities` row `id`, or a history handle. For email: an `attach_file` "
            "id or a history email `activity_id`. For a task: the create echo or a "
            "`get_tasks_for_party` id. Never invent or guess."
        )
    )
