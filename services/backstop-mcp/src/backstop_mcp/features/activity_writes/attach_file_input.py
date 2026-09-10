"""Discriminated `attach_file` input: `document` upload vs `.msg`/`.eml` email import.

`content` is standard base64 of the raw file. The command gzip+base64-encodes it for
Backstop's `data` field. Author is the authenticated caller, not a parameter.
"""

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, StringConstraints, model_validator

from backstop_mcp.features.activity_writes._party_target_input import (
    PartyTargetInput,
    SecondaryPartyInput,
)

__all__ = [
    "ATTACH_FILE_INPUT_DESCRIPTION",
    "AttachFileInput",
    "DocumentFileInput",
    "EmailFileInput",
]

ATTACH_FILE_INPUT_DESCRIPTION = (
    "Required. The file to attach. Discriminated by `kind`: `document` or `email` "
    "(real `.msg`/`.eml` import). Needs `search_type`, `file_name`, `content`, and "
    "exactly one of `party_id` or `search` — `party_id` alone is rejected. Do not "
    "generate `content` yourself; always use a file-encoding tool when one is available."
)

_NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

_EMAIL_FORMATS: dict[str, Literal["eml", "msg"]] = {".eml": "eml", ".msg": "msg"}


class _FileBlobInput(BaseModel):
    """The file blob every attach_file variant carries."""

    file_name: _NonEmptyStr = Field(
        description=(
            "Required. Original file name including extension (e.g. memo.pdf or reply.eml). "
            "For `kind=email`, a `.eml` or `.msg` suffix supplies `email_format` when omitted."
        )
    )
    content: _NonEmptyStr = Field(
        description=(
            "Standard base64 of the raw file bytes. Do not generate this string yourself — "
            "always use a file-encoding tool when one is available. Do not gzip or "
            "URL-safe-encode; this tool does that for Backstop. Practical ceiling for an "
            "LLM-driven call is much smaller than the 20 MB hard cap."
        )
    )
    activity_tag_ids: tuple[str, ...] = Field(
        default=(),
        description="Activity-tag ids from `list_activity_tags`. Empty when none apply.",
    )


class DocumentFileInput(PartyTargetInput, SecondaryPartyInput, _FileBlobInput):
    """A document uploaded against a party (`POST /documents`)."""

    kind: Literal["document"] = Field(
        description="Upload a document. Creates a documents record attached to the party."
    )
    title: _NonEmptyStr | None = Field(
        default=None,
        description="Title written on the document. Defaults to `file_name` when omitted.",
    )
    description: _NonEmptyStr | None = Field(
        default=None,
        description="Optional document description. Omit when there is none.",
    )
    effective_date: date | None = Field(
        default=None,
        description="Calendar day on the document, for backdating. Omit to use today.",
    )


class EmailFileInput(PartyTargetInput, _FileBlobInput):
    """A real `.msg`/`.eml` import (`POST /emails` with `data`)."""

    kind: Literal["email"] = Field(
        description=(
            "Import a real email file. Same `/emails` collection as `log_activity(kind=email)`, "
            "but this path sends the message blob. Use `log_activity` for a metadata stub."
        )
    )
    email_format: Literal["eml", "msg"] | None = Field(
        default=None,
        description=(
            "Backstop `emailFormat`: eml or msg. Inferred from `file_name` when omitted. "
            "Required when the extension is neither .eml nor .msg."
        ),
    )
    display_subject: _NonEmptyStr | None = Field(
        default=None,
        description=(
            "Display subject written on the email. Omit when Backstop should parse it "
            "from the file."
        ),
    )

    @model_validator(mode="after")
    def _infer_email_format(self) -> Self:
        if self.email_format is not None:
            return self
        lower_name = self.file_name.lower()
        for suffix, fmt in _EMAIL_FORMATS.items():
            if lower_name.endswith(suffix):
                return self.model_copy(update={"email_format": fmt})
        raise ValueError("email_format is required when file_name is not .eml or .msg")


type AttachFileInput = Annotated[
    DocumentFileInput | EmailFileInput,
    Field(discriminator="kind", description=ATTACH_FILE_INPUT_DESCRIPTION),
]
