import json

import pytest
from kiota_serialization_json.json_parse_node_factory import JsonParseNodeFactory
from msgraph.generated.models.attachment import Attachment
from msgraph.generated.models.file_attachment import FileAttachment

from office_365_mcp.shared.attachments import ATTACHMENT_FIELDS, AttachmentSummary
from office_365_mcp.shared.handles import EventAttachmentHandle, MailAttachmentHandle

_MAIL_ATTACHMENT_URI = MailAttachmentHandle(
    "AAMkAGI2SYNTHETIC-0001=", "AAMkAGI2SYNTHETIC-attachment-0002="
).uri
_EVENT_ATTACHMENT_URI = EventAttachmentHandle(
    "AAMkSYNTHETIC-cal-0003=", "AAMkAGI2SYNTHETIC-0004=", "AAMkAGI2SYNTHETIC-attachment-0005="
).uri
_CONTENT_BYTES = "U1lOVEhFVElDLWNvbnRlbnQtYnl0ZXM="


def _parsed(payload: dict[str, object]) -> Attachment:
    node = JsonParseNodeFactory().get_root_parse_node(
        "application/json", json.dumps(payload).encode()
    )
    attachment = node.get_object_value(Attachment)
    assert attachment is not None
    return attachment


@pytest.mark.parametrize(
    ("odata_type", "kind"),
    [
        ("#microsoft.graph.fileAttachment", "file"),
        ("#microsoft.graph.itemAttachment", "item"),
        ("#microsoft.graph.referenceAttachment", "reference"),
        ("#microsoft.graph.syntheticAttachment", "unknown"),
    ],
)
def test_the_kind_follows_the_odata_type_that_graph_sends(odata_type: str, kind: str) -> None:
    attachment = _parsed({"@odata.type": odata_type, "id": "AAMkAGI2SYNTHETIC-attachment-0002="})

    row = AttachmentSummary.from_attachment(attachment, uri=_MAIL_ATTACHMENT_URI)

    assert row.kind == kind


def test_an_attachment_with_no_odata_type_is_of_unknown_kind() -> None:
    row = AttachmentSummary.from_attachment(
        _parsed({"id": "AAMkAGI2SYNTHETIC-attachment-0002="}), uri=_MAIL_ATTACHMENT_URI
    )

    assert row.kind == "unknown"


def test_a_row_carries_the_base_properties_of_a_file_attachment() -> None:
    attachment = _parsed(
        {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "id": "AAMkAGI2SYNTHETIC-attachment-0002=",
            "lastModifiedDateTime": "2026-04-02T03:41:29Z",
            "name": "Synthetic invoice.docx",
            "contentType": (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            "size": 13068,
            "isInline": False,
            "contentBytes": _CONTENT_BYTES,
        }
    )

    row = AttachmentSummary.from_attachment(attachment, uri=_MAIL_ATTACHMENT_URI)

    assert row == AttachmentSummary(
        uri=_MAIL_ATTACHMENT_URI,
        name="Synthetic invoice.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size=13068,
        is_inline=False,
        kind="file",
        last_modified_at="2026-04-02T03:41:29+00:00",
    )


def test_a_row_never_carries_the_content_bytes() -> None:
    attachment = _parsed(
        {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "id": "AAMkAGI2SYNTHETIC-attachment-0002=",
            "contentBytes": _CONTENT_BYTES,
        }
    )

    row = AttachmentSummary.from_attachment(attachment, uri=_MAIL_ATTACHMENT_URI)

    assert _CONTENT_BYTES not in row.model_dump_json()


def test_the_selected_fields_are_base_properties_and_never_the_content() -> None:
    assert set(ATTACHMENT_FIELDS) <= set(Attachment().get_field_deserializers())
    assert "contentBytes" in FileAttachment().get_field_deserializers()
    assert "contentBytes" not in ATTACHMENT_FIELDS


@pytest.mark.parametrize("uri", [_MAIL_ATTACHMENT_URI, _EVENT_ATTACHMENT_URI])
def test_a_row_takes_the_handle_that_the_caller_gives(uri: str) -> None:
    row = AttachmentSummary.from_attachment(
        FileAttachment(id="AAMkAGI2SYNTHETIC-attachment-0002="), uri=uri
    )

    assert row.uri == uri


def test_a_property_that_graph_leaves_out_stays_null() -> None:
    row = AttachmentSummary.from_attachment(Attachment(), uri=_EVENT_ATTACHMENT_URI)

    assert row == AttachmentSummary(
        uri=_EVENT_ATTACHMENT_URI,
        name=None,
        content_type=None,
        size=None,
        is_inline=None,
        kind="unknown",
        last_modified_at=None,
    )
