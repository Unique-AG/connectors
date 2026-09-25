"""Admin-set RJSF config for the content_metadata tool."""

from typing import Annotated

from pydantic import BaseModel, Field
from unique_toolkit._common.pydantic.rjsf_tags import RJSFMetaTag
from unique_toolkit.content.smart_rules import UniqueQLField

# Fields the platform stamps on content itself — identifiers, source
# links, owners — not business metadata a caller would filter on.
# Excluded by default so they don't drown out fields worth filtering.
_DEFAULT_EXCLUDED_FIELDS = [
    "key",
    "url",
    "title",
    "folderId",
    "mimeType",
    "companyId",
    "contentId",
    "validAsOf",
    "folderIdPath",
    "externalFileOwner",
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
    max_values_per_field: int = Field(
        default=1000,
        ge=1,
        description=(
            "Ceiling on distinct values returned per field. A caller's "
            "limit is clamped to this."
        ),
    )
    max_concurrent_scope_lookups: int = 25
