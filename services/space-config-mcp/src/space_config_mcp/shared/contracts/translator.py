from typing import ClassVar

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic.alias_generators import to_camel

_CAMEL: ConfigDict = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ProcessingStep(BaseModel):
    """A pre- or post-processing step applied during translation."""

    model_config: ClassVar[ConfigDict] = _CAMEL

    name: str = Field(description="Step identifier, e.g. 'translation_glossary'.")
    value: bool = Field(description="Whether the step is active.")
    language: str | None = Field(
        default=None,
        description=(
            "Restrict this step to a specific language, e.g. 'German'. Omit to apply to all."
        ),
    )


class TranslationConfig(BaseModel):
    """Configuration for a TranslatorV2 module stored under configuration.TranslationConfig."""

    model_config: ClassVar[ConfigDict] = _CAMEL

    language_model_translation: str | None = Field(
        default=None,
        description="Model used for the translation step, e.g. 'AZURE_GPT_4o_2024_1120'.",
    )
    language_model_language_detection: str | None = Field(
        default=None,
        description="Model used for language detection.",
    )
    temperature_translation: float | None = Field(
        default=None,
        ge=0,
        le=2,
        description="Sampling temperature for translation (0–2). Lower = more deterministic.",
    )
    streaming_activated: bool | None = Field(
        default=None,
        description="Stream translation tokens to the UI as they arrive.",
    )
    custom_output_token_limit: int | None = Field(
        default=None,
        description=(
            "Override the model's default output token limit. Set to null to use the model default."
        ),
    )
    scope_id_translation_glossary: str | None = Field(
        default=None,
        description="Scope ID of the KB folder containing the translation glossary.",
    )
    file_name_translation_glossary: str | None = Field(
        default=None,
        description="File name of the glossary file within the glossary scope.",
    )
    pre_processing: list[ProcessingStep] | None = Field(
        default=None,
        description=(
            "Steps applied before translation, e.g. glossary injection. "
            "Providing this list replaces all existing pre-processing steps."
        ),
    )
    post_processing: list[ProcessingStep] | None = Field(
        default=None,
        description=(
            "Steps applied after translation, e.g. character replacements. "
            "Providing this list replaces all existing post-processing steps."
        ),
    )
