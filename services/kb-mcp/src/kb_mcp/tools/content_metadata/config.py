"""Admin-set RJSF config for the content_metadata tool."""

from typing import Annotated

from pydantic import BaseModel, Field
from unique_toolkit._common.pydantic.rjsf_tags import RJSFMetaTag
from unique_toolkit.content.smart_rules import UniqueQLField

# System-assigned per-file identifiers, not business/domain metadata a
# caller would ever build a search filter on — excluded from the catalog by
# default so they don't drown out fields actually worth filtering on.
_DEFAULT_EXCLUDED_FIELDS = [
    "folderIdPath",
    "key",
    "title",
    "folderId",
    "mimeType",
    "companyId",
    "contentId",
    "validAsOf",
]


class ContentMetadataToolConfig(BaseModel):
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
    excluded_fields: list[str] = Field(
        default_factory=lambda: list(_DEFAULT_EXCLUDED_FIELDS)
    )
    max_concurrent_scope_lookups: int = 25
