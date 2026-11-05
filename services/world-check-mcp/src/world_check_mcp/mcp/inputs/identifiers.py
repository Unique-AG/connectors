from typing import Annotated

from pydantic import Field

GroupId = Annotated[
    str,
    Field(min_length=1, description="Group id from `list_groups`. It owns the case template."),
]
CaseArgument = Annotated[
    str,
    Field(
        min_length=1,
        description=(
            "Internal caseSystemId, or the exact external caseId. "
            "Not a person's name or a profile referenceId."
        ),
    ),
]
ExternalCaseId = Annotated[
    str,
    Field(
        min_length=1,
        description="External caseId. `get_case_reference` returns its caseSystemId.",
    ),
]
ReferenceId = Annotated[
    str,
    Field(
        min_length=1,
        description="World-Check record referenceId from a screening match, not its resultId.",
    ),
]
