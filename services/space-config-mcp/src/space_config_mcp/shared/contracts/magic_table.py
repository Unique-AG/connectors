from typing import ClassVar

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic.alias_generators import to_camel

_CAMEL: ConfigDict = ConfigDict(alias_generator=to_camel, populate_by_name=True)
_SNAKE: ConfigDict = ConfigDict(populate_by_name=True)


class MagicTableExportAssistant(BaseModel):
    """An assistant shown in the Magic Table export menu."""

    label: str = Field(description="Button label shown in the export menu.")
    prompt: str = Field(description="Prompt sent to the assistant when the user triggers export.")
    assistant_id: str = Field(description="ID of the assistant to invoke.")


class MagicTableSpaceSettings(BaseModel):
    """Space-level settings for a Magic Table space (space.settings.magicTableConfig)."""

    model_config: ClassVar[ConfigDict] = _CAMEL

    answer_library: bool | None = Field(
        default=None,
        description="Show the Answer Library section to space members.",
    )
    hide_sheet_status: bool | None = Field(
        default=None,
        description="Hide the sheet status indicator from users.",
    )
    export_assistants: list[MagicTableExportAssistant] | None = Field(
        default=None,
        description=(
            "Assistants available in the export menu. "
            "Providing this list replaces all existing export assistants."
        ),
    )
    answer_library_access_entity_ids: list[str] | None = Field(
        default=None,
        description=(
            "Restrict Answer Library access to these entity IDs. "
            "Omit to show it to every space member."
        ),
    )
    disable_notifications_by_default: bool | None = Field(
        default=None,
        description="Hide the sheet notification toggle and keep default assignee emails.",
    )


class RfpColumn(BaseModel):
    """Definition of a single column in the Magic Table (RfpAgent)."""

    model_config: ClassVar[ConfigDict] = _SNAKE

    name: str = Field(
        description=(
            "Column identifier. "
            "Built-in names: Section, Question, Answers, References, HallucinationScore."
        )
    )
    system_prompt: str | None = Field(
        default=None,
        description="System prompt for the LLM that fills this column.",
    )
    assistant_prompt: str | None = Field(
        default=None,
        description="Trigger / user prompt template for the LLM that fills this column.",
    )
    width: int | None = Field(
        default=None,
        description="Column width in pixels.",
    )
    editable: bool | None = Field(
        default=None,
        description="Whether users can edit cell values in this column.",
    )


class RfpModuleConfig(BaseModel):
    """Module-level configuration for an RfpAgent (Magic Table) module."""

    model_config: ClassVar[ConfigDict] = _CAMEL

    language_model: str | None = Field(
        default=None,
        description="Default language model for all columns that don't override it.",
    )
    columns: list[RfpColumn] | None = Field(
        default=None,
        description=(
            "Full column list. Providing this replaces all existing columns. "
            "Use get_module to fetch and preserve columns you don't want to change."
        ),
    )
    auto_reprocess_on_source_add: bool | None = Field(
        default=None,
        description=(
            "If True, automatically reprocess all rows when new sources are added. "
            "If False (default), users trigger reprocessing manually."
        ),
    )
    hallucination_enabled: bool | None = Field(
        default=None,
        description="Enable the hallucination check column.",
    )

    question_extraction_language_model: str | None = Field(
        default=None,
        description="Model used to extract questions from uploaded documents.",
    )
    question_extraction_use_full_document: bool | None = Field(
        default=None,
        description=(
            "Extract questions from the full document in one call rather than chunk-by-chunk. "
            "Falls back to chunked mode if the document exceeds the token limit."
        ),
    )
    question_extraction_max_rows: int | None = Field(
        default=None,
        ge=1,
        description="Maximum number of questions to extract per document.",
    )
