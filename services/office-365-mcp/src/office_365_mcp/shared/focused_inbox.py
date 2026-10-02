from typing import Literal, Self

from msgraph.generated.models.inference_classification_override import (
    InferenceClassificationOverride,
)
from msgraph.generated.models.inference_classification_type import InferenceClassificationType
from pydantic import BaseModel, Field

type ClassifyAs = Literal["focused", "other"]


class FocusedOverride(BaseModel):
    sender_address: str = Field(
        description=(
            "The SMTP address of the sender. Each address has at most one row. If this "
            "deployment exposes outlook_set_focused_override, use this value as `sender` in that "
            "tool."
        )
    )
    sender_name: str | None = Field(
        description=(
            "The display name that Outlook stores with the address. It is null when Graph gives "
            "no name."
        )
    )
    classify_as: ClassifyAs | None = Field(
        description=(
            "The tab that holds all future mail from this sender. `focused` means the Focused "
            "tab. `other` means the Other tab. It is null when Graph gives none."
        )
    )

    @classmethod
    def from_override(cls, override: InferenceClassificationOverride) -> Self:
        sender = override.sender_email_address
        assert sender is not None and sender.address is not None, (
            "Graph returned an override with no sender address"
        )
        return cls(
            sender_address=sender.address,
            sender_name=sender.name,
            classify_as=_reported(override.classify_as),
        )


def _reported(classify_as: InferenceClassificationType | None) -> ClassifyAs | None:
    match classify_as:
        case None:
            return None
        case InferenceClassificationType.Focused:
            return "focused"
        case InferenceClassificationType.Other:
            return "other"
