"""Per-kind attach commands, size-cap rejection, and Backstop 413 remapping."""

import base64
import gzip
from collections.abc import AsyncGenerator

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.activity_writes import (
    AttachFileCommand,
    AuthorDto,
    DocumentFileInput,
    EmailFileInput,
    encode_file_data,
    get_attach_document_command_factory,
    get_attach_email_command_factory,
    get_attach_file_command_factory,
)
from tests.helpers import BASE_URL, client_factory, credential, recorded_json_bodies
from tests.server.tools.helpers import object_dict

_AUTHOR = AuthorDto(id="su-author", user_name="bob.smith", name="Bob Smith")
_PARTY_ID = "27871657"
_ORG_ID = "341764767"
_DOC_ID = "88002233"
_EMAIL_ID = "77002233"
_RAW = b"hello memo"
_CONTENT = base64.b64encode(_RAW).decode("ascii")


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def _created(resource_type: str, resource_id: str, **attrs: object) -> httpx.Response:
    return httpx.Response(
        201,
        json={"data": {"id": resource_id, "type": resource_type, "attributes": attrs}},
    )


def _data(body: dict[str, object]) -> dict[str, object]:
    return object_dict(body["data"])


def _attributes(body: dict[str, object]) -> dict[str, object]:
    return object_dict(_data(body)["attributes"])


def _decode_backstop_data(data: str) -> bytes:
    padded = data + "=" * (-len(data) % 4)
    return gzip.decompress(base64.urlsafe_b64decode(padded))


def make_command(client: BackstopClient) -> AttachFileCommand:
    return get_attach_file_command_factory(
        attach_document_command=get_attach_document_command_factory(client),
        attach_email_command=get_attach_email_command_factory(client),
    )


def _document(**overrides: object) -> DocumentFileInput:
    values: dict[str, object] = {
        "kind": "document",
        "search_type": "people",
        "party_id": _PARTY_ID,
        "file_name": "memo.pdf",
        "content": _CONTENT,
    }
    return DocumentFileInput.model_validate({**values, **overrides})


def _email(**overrides: object) -> EmailFileInput:
    values: dict[str, object] = {
        "kind": "email",
        "search_type": "people",
        "party_id": _PARTY_ID,
        "file_name": "reply.eml",
        "content": _CONTENT,
    }
    return EmailFileInput.model_validate({**values, **overrides})


class TestEncodeFileData:
    def test_gzips_then_urlsafe_base64_without_padding(self) -> None:
        encoded = encode_file_data(_CONTENT)

        assert "=" not in encoded
        assert _decode_backstop_data(encoded) == _RAW

    def test_rejects_over_cap_before_any_caller_could_post(self) -> None:
        with pytest.raises(ToolError, match="before calling Backstop") as raised:
            encode_file_data(base64.b64encode(b"too-big").decode("ascii"), max_bytes=3)

        assert "No request was sent to Backstop" in str(raised.value)

    def test_rejects_invalid_base64(self) -> None:
        with pytest.raises(ToolError, match="not valid base64"):
            encode_file_data("@@@not-base64@@@")


class TestAttachFileCommand:
    @respx.mock
    async def test_document_posts_top_level_documents_with_attached_to(
        self, client: BackstopClient
    ) -> None:
        route = respx.post(f"{BASE_URL}/documents").mock(
            return_value=_created("documents", _DOC_ID, title="memo.pdf")
        )

        result = await make_command(client).run(
            activity=_document(), party_id=_PARTY_ID, author=_AUTHOR
        )

        assert result.id == _DOC_ID
        assert result.kind == "document"
        assert route.call_count == 1
        body = recorded_json_bodies(route)[0]
        attributes = _attributes(body)
        assert _data(body)["type"] == "documents"
        assert attributes["title"] == "memo.pdf"
        assert attributes["documentName"] == "memo.pdf"
        assert _decode_backstop_data(str(attributes["data"])) == _RAW
        assert attributes["attachedTo"] == {
            "resourceId": _PARTY_ID,
            "resourceType": "PersonBean",
            "resourceLink": f"/people/{_PARTY_ID}",
        }
        assert object_dict(attributes["author"])["resourceId"] == _AUTHOR.id
        assert "effectiveDate" in attributes

    @respx.mock
    async def test_document_links_a_secondary_party_without_repeating_the_parent(
        self, client: BackstopClient
    ) -> None:
        route = respx.post(f"{BASE_URL}/documents").mock(
            return_value=_created("documents", _DOC_ID)
        )

        await make_command(client).run(
            activity=_document(
                search_type="organizations",
                party_id=_ORG_ID,
                secondary_party_id=_PARTY_ID,
                secondary_search_type="people",
            ),
            party_id=_ORG_ID,
            author=_AUTHOR,
            secondary_party_id=_PARTY_ID,
        )

        attributes = _attributes(recorded_json_bodies(route)[0])
        assert attributes["linkedResources"] == [
            {
                "resourceId": _PARTY_ID,
                "resourceType": "PersonBean",
                "resourceLink": f"/people/{_PARTY_ID}",
            }
        ]
        assert object_dict(attributes["attachedTo"])["resourceId"] == _ORG_ID

    @respx.mock
    async def test_email_posts_data_and_inferred_eml_format(self, client: BackstopClient) -> None:
        route = respx.post(f"{BASE_URL}/emails").mock(return_value=_created("emails", _EMAIL_ID))

        result = await make_command(client).run(
            activity=_email(), party_id=_PARTY_ID, author=_AUTHOR
        )

        assert result.id == _EMAIL_ID
        assert result.kind == "email"
        attributes = _attributes(recorded_json_bodies(route)[0])
        assert attributes["emailFormat"] == "eml"
        assert _decode_backstop_data(str(attributes["data"])) == _RAW
        assert object_dict(attributes["createdBy"])["resourceId"] == _AUTHOR.id
        assert attributes["resources"] == [
            {
                "resourceId": _PARTY_ID,
                "resourceType": "PersonBean",
                "resourceLink": f"/people/{_PARTY_ID}",
            }
        ]

    @respx.mock
    async def test_over_cap_file_does_not_call_backstop(
        self, client: BackstopClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "backstop_mcp.features.activity_writes.commands._attachment_utils.ATTACH_FILE_MAX_BYTES",
            3,
        )
        route = respx.post(f"{BASE_URL}/documents").mock(
            return_value=_created("documents", _DOC_ID)
        )
        activity = _document(content=base64.b64encode(b"too-big").decode("ascii"))

        with pytest.raises(ToolError, match="before calling Backstop"):
            await make_command(client).run(
                activity=activity,
                party_id=_PARTY_ID,
                author=_AUTHOR,
            )

        assert route.call_count == 0

    @respx.mock
    async def test_backstop_413_is_not_the_local_cap_message(self, client: BackstopClient) -> None:
        respx.post(f"{BASE_URL}/documents").mock(
            return_value=httpx.Response(
                413, json={"errors": [{"title": "Request entity too large"}]}
            )
        )

        with pytest.raises(ToolError, match="HTTP 413") as raised:
            await make_command(client).run(activity=_document(), party_id=_PARTY_ID, author=_AUTHOR)

        message = str(raised.value)
        assert "before calling Backstop" not in message
        assert "request was sent" in message

    def test_email_without_format_or_known_extension_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="email_format"):
            EmailFileInput.model_validate(
                {
                    "kind": "email",
                    "search_type": "people",
                    "party_id": _PARTY_ID,
                    "file_name": "notes.txt",
                    "content": _CONTENT,
                }
            )
