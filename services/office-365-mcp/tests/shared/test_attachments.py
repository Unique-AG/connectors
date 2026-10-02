import base64
import json

import httpx
import pytest
import respx
from kiota_serialization_json.json_parse_node_factory import JsonParseNodeFactory
from msgraph.generated.models.attachment import Attachment
from msgraph.generated.models.file_attachment import FileAttachment
from msgraph.generated.models.item_attachment import ItemAttachment
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.shared import attachments
from office_365_mcp.shared.attachments import (
    ATTACHMENT_FIELDS,
    MAX_BYTES,
    MEGABYTE,
    STEP_MESSAGE_ATTACHMENTS,
    AttachmentKind,
    AttachmentRefusals,
    AttachmentSummary,
    file_or_refusal,
    media_type,
    message_attachments,
    refusal_before_download,
)
from office_365_mcp.shared.handles import (
    EventAttachmentHandle,
    MailAttachmentHandle,
    MailMessageHandle,
    mail_attachment_handle,
)
from office_365_mcp.shared.seam import FileFromGraph

from .conftest import GRAPH_V1

_MESSAGE_ID = "AAMkAGI2SYNTHETIC-0001="
_MESSAGES_PATH = "/me/messages/AAMkAGI2SYNTHETIC-0001%3D/attachments"
_MAIL_ATTACHMENT_URI = MailAttachmentHandle(_MESSAGE_ID, "AAMkAGI2SYNTHETIC-attachment-0002=").uri
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


def _row(attachment_id: str, *, name: str = "Invoice.pdf") -> dict[str, object]:
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "id": attachment_id,
        "name": name,
        "contentType": "application/pdf",
        "size": 13068,
        "isInline": False,
        "lastModifiedDateTime": "2026-03-04T09:15:00Z",
    }


class TestTheMessageListing:
    async def test_each_row_carries_the_handle_of_its_attachment_in_the_order_graph_sent(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_MESSAGES_PATH).mock(
            return_value=httpx.Response(
                200, json={"value": [_row("first-id="), _row("second-id=", name="Logo.png")]}
            )
        )

        found = await message_attachments(client, handle=MailMessageHandle(_MESSAGE_ID))

        assert [mail_attachment_handle(row.uri) for row in found.items] == [
            MailAttachmentHandle(_MESSAGE_ID, "first-id="),
            MailAttachmentHandle(_MESSAGE_ID, "second-id="),
        ]
        assert [row.name for row in found.items] == ["Invoice.pdf", "Logo.png"]
        assert found.capped is False

    async def test_it_selects_the_shared_fields_and_declares_the_immutable_id_space(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.get(_MESSAGES_PATH).mock(
            return_value=httpx.Response(200, json={"value": [_row("first-id=")]})
        )

        _ = await message_attachments(client, handle=MailMessageHandle(_MESSAGE_ID))

        request = route.calls.last.request
        assert route.call_count == 1
        assert request.url.params["$select"].split(",") == list(ATTACHMENT_FIELDS)
        assert 'IdType="ImmutableId"' in request.headers["prefer"]

    async def test_a_listing_longer_than_the_scan_limit_is_capped(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(attachments, "MAX_SCANNED_ITEMS", 1)
        _ = graph.get(_MESSAGES_PATH).mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [_row("first-id="), _row("second-id=")],
                    "@odata.nextLink": f"{GRAPH_V1}{_MESSAGES_PATH}?$skiptoken=second",
                },
            )
        )

        found = await message_attachments(client, handle=MailMessageHandle(_MESSAGE_ID))

        assert len(found.items) == 1
        assert found.capped is True

    async def test_a_mailbox_lists_that_mailbox_instead_of_me(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        shared = graph.get(
            "/users/alex@example.invalid/messages/AAMkAGI2SYNTHETIC-0001%3D/attachments"
        ).mock(return_value=httpx.Response(200, json={"value": [_row("first-id=")]}))
        mine = graph.get(_MESSAGES_PATH)

        found = await message_attachments(
            client, handle=MailMessageHandle(_MESSAGE_ID), mailbox="alex@example.invalid"
        )

        assert shared.called
        assert mine.call_count == 0
        assert len(found.items) == 1

    def test_the_graph_step_is_the_one_the_dashboard_knows(self) -> None:
        assert STEP_MESSAGE_ATTACHMENTS == "message_attachments"


_REFUSALS = AttachmentRefusals(
    an_item="an item",
    a_link="a link",
    no_size="no size",
    nothing_came_back="nothing came back",
    too_large=lambda size: f"too large at {size}",
)


def _summary(
    *,
    kind: AttachmentKind = "file",
    size: int | None = 20,
    name: str | None = "Invoice.pdf",
    content_type: str | None = "application/pdf",
) -> AttachmentSummary:
    return AttachmentSummary(
        uri=_MAIL_ATTACHMENT_URI,
        name=name,
        content_type=content_type,
        size=size,
        is_inline=False,
        kind=kind,
        last_modified_at=None,
    )


def test_the_cap_is_ten_binary_megabytes() -> None:
    assert MEGABYTE == 1024 * 1024
    assert MAX_BYTES == 10 * MEGABYTE


class TestWhatIsRefusedBeforeAnyDownload:
    @pytest.mark.parametrize("size", [None, 0, 20, MAX_BYTES + 1])
    def test_an_attached_item_is_refused_whatever_its_size(self, size: int | None) -> None:
        assert refusal_before_download(_summary(kind="item", size=size), _REFUSALS) == "an item"

    @pytest.mark.parametrize("size", [None, 0, 20, MAX_BYTES + 1])
    def test_a_link_is_refused_whatever_its_size(self, size: int | None) -> None:
        assert refusal_before_download(_summary(kind="reference", size=size), _REFUSALS) == "a link"

    def test_a_file_with_no_reported_size_is_refused(self) -> None:
        assert refusal_before_download(_summary(size=None), _REFUSALS) == "no size"

    def test_a_file_one_byte_above_the_cap_is_refused_with_its_own_size(self) -> None:
        refused = refusal_before_download(_summary(size=MAX_BYTES + 1), _REFUSALS)

        assert refused == f"too large at {MAX_BYTES + 1}"

    @pytest.mark.parametrize("size", [0, 20, MAX_BYTES])
    def test_a_file_within_the_cap_is_not_refused(self, size: int) -> None:
        assert refusal_before_download(_summary(size=size), _REFUSALS) is None

    def test_an_unrecognized_kind_is_decided_by_its_size_like_a_file(self) -> None:
        assert refusal_before_download(_summary(kind="unknown", size=None), _REFUSALS) == "no size"
        assert refusal_before_download(_summary(kind="unknown", size=20), _REFUSALS) is None


def _file_attachment(content: bytes | None) -> FileAttachment:
    return FileAttachment(
        id="AAMkAGI2SYNTHETIC-attachment-0002=",
        content_bytes=content,
    )


class TestWhatTheDownloadBecomes:
    def test_the_bytes_become_a_file_with_its_name_and_media_type(self) -> None:
        body = b"%PDF-1.7\x00\xff synthetic bytes"

        file = file_or_refusal(_summary(size=len(body)), _file_attachment(body), _REFUSALS)

        assert isinstance(file, FileFromGraph)
        assert file.data == body
        resource = file.to_resource_content().resource
        assert resource.mime_type == "application/pdf"
        assert resource.uri == "file:///Invoice.pdf"

    def test_an_empty_file_that_graph_reports_as_empty_comes_back_empty(self) -> None:
        file = file_or_refusal(_summary(size=0), _file_attachment(b""), _REFUSALS)

        assert isinstance(file, FileFromGraph)
        assert file.data == b""

    @pytest.mark.parametrize("downloaded", [None, FileAttachment(), ItemAttachment()])
    def test_nothing_for_an_attachment_that_holds_data_is_the_nothing_came_back_refusal(
        self, downloaded: Attachment | None
    ) -> None:
        assert file_or_refusal(_summary(size=20), downloaded, _REFUSALS) == "nothing came back"

    def test_empty_bytes_for_an_attachment_that_holds_data_are_the_same_refusal(self) -> None:
        refused = file_or_refusal(_summary(size=20), _file_attachment(b""), _REFUSALS)

        assert refused == "nothing came back"

    def test_the_bytes_never_leave_through_the_summary(self) -> None:
        body = b"synthetic bytes"

        file = file_or_refusal(_summary(size=len(body)), _file_attachment(body), _REFUSALS)

        assert isinstance(file, FileFromGraph)
        assert base64.b64encode(body).decode() not in _summary().model_dump_json()


class TestTheMediaType:
    @pytest.mark.parametrize(
        ("content_type", "body", "expected"),
        [
            ("application/pdf", b"%PDF", "application/pdf"),
            ("Application/PDF; name=Invoice.pdf", b"%PDF", "application/pdf"),
            ("text/csv", b"name,value\r\n", "text/csv"),
            ("text/csv", "name,value".encode("utf-16"), "application/octet-stream"),
            ("application/pdf", b"\xff\xfe", "application/pdf"),
            (None, b"%PDF", "application/octet-stream"),
            ("", b"%PDF", "application/octet-stream"),
            ("application", b"%PDF", "application/octet-stream"),
            ("/pdf", b"%PDF", "application/octet-stream"),
            ("pdf/", b"%PDF", "application/octet-stream"),
        ],
    )
    def test_the_reported_type_is_kept_when_it_is_a_type_and_subtype_that_fits_the_bytes(
        self, content_type: str | None, body: bytes, expected: str
    ) -> None:
        assert media_type(content_type, body) == expected
