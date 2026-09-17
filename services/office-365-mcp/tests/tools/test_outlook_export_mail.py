"""Every byte here is synthesised. None came from a real mailbox."""

from collections.abc import Mapping
from typing import cast
from urllib.parse import unquote

import httpx
import pytest
import respx
from fastmcp import Client, FastMCP
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from fastmcp.utilities.types import File
from mcp.types import Tool
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared.handles import MailMessageHandle
from office_365_mcp.tools.outlook_export_mail import (
    MAX_EXPORT_BYTES,
    TOOL_NAME,
    EmlFile,
    export_mail,
    register,
)

_IMMUTABLE_ID = "AAMkAGI2SYNTHETIC-immutable-0001="

_PATH = "/me/messages/AAMkAGI2SYNTHETIC-immutable-0001%3D/$value"

_HANDLE = MailMessageHandle(_IMMUTABLE_ID)

_MIME = (
    b"Received: from mail.vance.invalid (10.0.0.1) by outlook.invalid\r\n"
    + b"Authentication-Results: spf=pass\r\n"
    + b"From: Bob Vance <bob@vance.invalid>\r\n"
    + b"To: Ada <ada@contoso.invalid>\r\n"
    + b"Subject: Invoice 4471\r\n"
    + b"Content-Type: text/plain\r\n"
    + b"\r\n"
    + b"The invoice never arrived.\r\n"
)


def _mime_with_subject(subject: bytes) -> bytes:
    return b"From: bob@vance.invalid\r\nSubject: " + subject + b"\r\n\r\nbody\r\n"


def _filename_of(exported: EmlFile) -> str:
    """The name as it reaches a client: rendered into the resource URI, then read back out of it.

    Read through the rendering rather than off the object, because the URI is where an unsafe name
    would do its damage and the only place the escaping shows.
    """
    return unquote(str(exported.to_resource_content().resource.uri).removeprefix("file:///"))


def _exports(graph: respx.MockRouter, mime: bytes = _MIME) -> respx.Route:
    return graph.get(_PATH).mock(
        return_value=httpx.Response(
            200, content=mime, headers={"Content-Type": "application/octet-stream"}
        )
    )


class TestWhatItAsksGraphFor:
    async def test_it_reads_the_messages_own_mime_rather_than_its_properties(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`$value` is the whole difference between this tool and outlook_read_mail."""
        route = _exports(graph)

        _ = await export_mail(client, handle=_HANDLE)

        assert route.calls.last.request.url.path.endswith("/$value")
        assert "$select" not in route.calls.last.request.url.params

    async def test_it_asks_for_the_immutable_id_space_as_the_reader_does(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """One handle has to behave identically in both readers, whatever Graph does with the
        header on a path id."""
        route = _exports(graph)

        _ = await export_mail(client, handle=_HANDLE)

        assert route.calls.last.request.headers["Prefer"] == 'IdType="ImmutableId"'

    async def test_it_makes_exactly_one_request(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The filename comes out of these bytes: a second request for the subject would be a
        second permission check and a second answer that can disagree with this one."""
        route = _exports(graph)

        _ = await export_mail(client, handle=_HANDLE)

        assert route.call_count == 1
        assert len(graph.calls) == 1


class TestWhatItReturns:
    async def test_it_hands_back_the_bytes_graph_sent_unchanged(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """An assembled `.eml` is a different message that looks like the original."""
        _ = _exports(graph)

        exported = await export_mail(client, handle=_HANDLE)

        assert exported.data == _MIME

    async def test_it_keeps_the_routing_headers_the_reader_withholds(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """outlook_read_mail never selects `internetMessageHeaders`. The MIME is those headers,
        and an export with them stripped is not the message Exchange stored."""
        _ = _exports(graph)

        exported = await export_mail(client, handle=_HANDLE)

        assert exported.data is not None
        assert b"Received: from mail.vance.invalid" in exported.data
        assert b"Authentication-Results: spf=pass" in exported.data

    async def test_it_publishes_the_media_type_a_mail_client_registers_for(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """FastMCP's `File` would compose `application/eml` from the format string, and nothing
        claims that type."""
        _ = _exports(graph)

        exported = await export_mail(client, handle=_HANDLE)

        assert exported.to_resource_content().resource.mime_type == "message/rfc822"

    async def test_it_names_the_file_after_the_messages_own_subject(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _exports(graph)

        exported = await export_mail(client, handle=_HANDLE)

        assert str(exported.to_resource_content().resource.uri) == "file:///Invoice%204471.eml"

    async def test_it_decodes_an_encoded_word_subject(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """RFC 2047 is how a non-ASCII subject travels, and the raw form is unreadable as a
        name."""
        _ = _exports(graph, _mime_with_subject(b"=?utf-8?B?UsOoZ2xlbWVudA==?="))

        exported = await export_mail(client, handle=_HANDLE)

        assert _filename_of(exported) == "Règlement.eml"


class TestTheFilenameIsSafeToPutInAUri:
    """The name is interpolated into `file:///{name}`, so a subject is URI syntax until it is
    reduced. A subject is written by whoever sent the message."""

    @pytest.mark.parametrize(
        ("subject", "expected"),
        [
            (b"Invoice 4471", "Invoice 4471.eml"),
            (b"Q3/Q4 forecast", "Q3-Q4 forecast.eml"),
            (b"Re: what now?", "Re- what now.eml"),
            (b"../../etc/passwd", "etc-passwd.eml"),
            (b"a#b?c&d", "a-b-c-d.eml"),
            (b"100% done", "100- done.eml"),
            (b"", "message.eml"),
            (b"...", "message.eml"),
            (b"///", "message.eml"),
        ],
    )
    async def test_it_reduces_a_subject_to_a_safe_stem(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        subject: bytes,
        expected: str,
    ) -> None:
        _ = _exports(graph, _mime_with_subject(subject))

        exported = await export_mail(client, handle=_HANDLE)

        assert _filename_of(exported) == expected

    async def test_a_format_character_cannot_make_the_name_lie_about_itself(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """A right-to-left override renders everything after it backwards, so a subject of
        `invoice<RLO>gpj.exe` shows in a file manager as `invoiceexe.jpg`. It is not URI syntax and
        a reduction aimed only at URI syntax would keep it."""
        _ = _exports(graph, _mime_with_subject("invoice\u202egpj.exe".encode()))

        exported = await export_mail(client, handle=_HANDLE)

        assert _filename_of(exported) == "invoice-gpj.exe.eml"

    async def test_it_falls_back_when_the_message_carries_no_subject_header(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _exports(graph, b"From: bob@vance.invalid\r\n\r\nbody\r\n")

        exported = await export_mail(client, handle=_HANDLE)

        assert _filename_of(exported) == "message.eml"

    async def test_it_bounds_the_name_however_long_the_subject_is(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _exports(graph, _mime_with_subject(b"A" * 4000))

        exported = await export_mail(client, handle=_HANDLE)

        assert len(_filename_of(exported)) <= 124

    async def test_a_subject_it_cannot_parse_costs_the_name_and_not_the_export(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The bytes are a stranger's. Nothing about them is worth failing an export already in
        hand."""
        mime = b"\x00\xff not headers at all \x00\r\n\r\nbody"
        _ = _exports(graph, mime)

        exported = await export_mail(client, handle=_HANDLE)

        assert exported.data == mime


class TestWhenItRefuses:
    async def test_it_refuses_a_message_larger_than_the_ceiling(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """A shortened `.eml` is a corrupt file rather than a smaller one."""
        _ = _exports(graph, _mime_with_subject(b"Big") + b"x" * MAX_EXPORT_BYTES)

        with pytest.raises(ToolError) as refusal:
            _ = await export_mail(client, handle=_HANDLE)

        assert str(MAX_EXPORT_BYTES) in str(refusal.value)
        assert "outlook_read_mail" in str(refusal.value), "it names what still works"
        assert "web_link" in str(refusal.value), "and how the user gets the file anyway"

    async def test_it_exports_a_message_exactly_at_the_ceiling(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The guard that keeps the one above from passing by refusing everything."""
        _ = _exports(graph, b"x" * MAX_EXPORT_BYTES)

        exported = await export_mail(client, handle=_HANDLE)

        assert exported.data is not None
        assert len(exported.data) == MAX_EXPORT_BYTES

    async def test_a_refused_read_arrives_as_the_graph_failure_it_is(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_PATH).mock(
            return_value=httpx.Response(403, json={"error": {"code": "ErrorAccessDenied"}})
        )

        with pytest.raises(GraphForbidden):
            _ = await export_mail(client, handle=_HANDLE)

    async def test_a_missing_message_arrives_as_the_graph_failure_it_is(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_PATH).mock(
            return_value=httpx.Response(404, json={"error": {"code": "ErrorItemNotFound"}})
        )

        with pytest.raises(GraphNotFound):
            _ = await export_mail(client, handle=_HANDLE)


class TestWhatItAdvertises:
    """Listing a tool needs no token, so this runs against a bare server. Calling one does, and
    `test_outlook_export_mail_surface.py` is where that happens."""

    @pytest.fixture
    async def listed(self, transport: httpx.AsyncClient) -> Mapping[str, Tool]:
        mcp: FastMCP = FastMCP("export-under-test", version="0")
        register(mcp, transport)
        async with Client(FastMCPTransport(mcp)) as client:
            return {tool.name: tool for tool in await client.list_tools()}

    async def test_it_says_it_changes_nothing(self, listed: Mapping[str, Tool]) -> None:
        annotations = listed[TOOL_NAME].annotations

        assert annotations is not None
        assert annotations.read_only_hint is True

    async def test_it_warns_that_the_file_is_a_strangers(self, listed: Mapping[str, Tool]) -> None:
        """This tool has no answer schema to carry the warning that every other reader puts in a
        field description, so the description is the only place it can live."""
        described = listed[TOOL_NAME].description or ""

        assert "untrusted" in described
        assert "instruction" in described

    async def test_it_sends_a_caller_reading_a_message_to_the_reader(
        self, listed: Mapping[str, Tool]
    ) -> None:
        """Bytes that are mostly base64 are the wrong answer to "what does this say", and the
        description is the only thing that stops a model asking this tool that question."""
        assert "outlook_read_mail" in (listed[TOOL_NAME].description or "")

    async def test_it_takes_the_handle_and_nothing_else(self, listed: Mapping[str, Tool]) -> None:
        """An export has no window, no limit and no projection: there is one message and one file.
        Any other argument would be a way to ask for part of it."""
        properties = cast("Mapping[str, object]", listed[TOOL_NAME].input_schema["properties"])

        assert set(properties) == {"uri"}


class TestTheFileType:
    def test_it_overrides_a_type_that_no_mail_client_claims(self) -> None:
        """The guard: `File`'s own composition is what this subclass exists to replace, and it
        would go on passing if `File` ever started returning the right type on its own."""
        composed = File(data=b"x", format="eml").to_resource_content()
        overridden = EmlFile(data=b"x", format="eml").to_resource_content()

        assert composed.resource.mime_type == "application/eml"
        assert overridden.resource.mime_type == "message/rfc822"
