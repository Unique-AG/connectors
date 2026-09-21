"""Admin-set RJSF config for the content_tree tool."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field
from unique_toolkit._common.pydantic.rjsf_tags import RJSFMetaTag
from unique_toolkit.content.smart_rules import UniqueQLField

MatchTarget = Literal["key", "path", "both"]


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
    # Its own default: 50 is a sensible page of search hits but would gut a
    # tree, which today renders uncapped.
    default_tree_limit: int = 1000
    default_min_score: float = 0.6
    default_match_on: MatchTarget = "both"
    default_case_sensitive: bool = False
    max_concurrent_scope_lookups: int = 25
