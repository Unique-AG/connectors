"""Admin-set RJSF config for the content_tree tool."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field
from unique_toolkit._common.pydantic.rjsf_tags import RJSFMetaTag
from unique_toolkit.content.smart_rules import Operator, Statement, UniqueQLField

MatchTarget = Literal["key", "path", "both"]

# Applied when metadata_filter is unset. Not the field's own default:
# UniqueQLField's schema declares string|null but its serializer returns
# dict|None, so any non-None default breaks admin-UI rendering. Kept as a
# Statement (`.to_dict()` per call) so no shared mutable dict is handed to
# downstream service calls.
DEFAULT_METADATA_FILTER_STATEMENT = Statement(
    operator=Operator.NOT_CONTAINS,
    path=["folderIdPath"],
    value="user-memory",
)


class ContentTreeToolConfig(BaseModel):
    # dict[str, Any] breaks the admin schema generator (RJSF can't infer
    # `items` for a nested array under Any); UniqueQLField avoids this.
    metadata_filter: Annotated[
        UniqueQLField,
        RJSFMetaTag(
            {
                "ui:options": {"customValidation": "uniqueql"},
                "anyOf": [
                    {
                        "ui:widget": "textarea",
                        "ui:placeholder": (
                            '{"operator": "equals", "value": "...", "path": ["fieldName"]}'
                        ),
                        "ui:emptyValue": "",
                    },
                    {},
                ],
            }
        ),
    ] = Field(default=None)
    default_limit: int = 50
    default_min_score: float = 0.6
    default_match_on: MatchTarget = "both"
    default_case_sensitive: bool = False
    max_concurrent_scope_lookups: int = 25
