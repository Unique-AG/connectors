"""`attach_file`: party resolve then the matching attach command."""

import base64
from collections.abc import AsyncGenerator

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.activity_writes import (
    AttachedFileResponse,
    AttachFileCommand,
    DocumentFileInput,
    get_attach_document_command_factory,
    get_attach_email_command_factory,
    get_attach_file_command_factory,
)
from backstop_mcp.features.activity_writes.tools.attach_file import attach_file
from backstop_mcp.features.resolution import NotFoundResponse
from backstop_mcp.features.system_users import SystemUserDto
from backstop_mcp.server.tools import TOOLS
from tests.features.party_resolver.helpers import ctx_never_elicit, make_resolve_party_query
from tests.helpers import BASE_URL, client_factory, collection, credential
from tests.server.tools.helpers import tool_model, tool_model_union

_PARTY_ID = "27871657"
_DOC_ID = "88002233"
_CALLER = SystemUserDto(id="su-author", user_name="bob.smith", name="Bob Smith")
_CONTENT = base64.b64encode(b"hello memo").decode("ascii")


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def make_command(client: BackstopClient) -> AttachFileCommand:
    return get_attach_file_command_factory(
        attach_document_command=get_attach_document_command_factory(client),
        attach_email_command=get_attach_email_command_factory(client),
    )


def _created(resource_type: str, resource_id: str, **attrs: object) -> httpx.Response:
    return httpx.Response(
        201,
        json={"data": {"id": resource_id, "type": resource_type, "attributes": attrs}},
    )


class TestAttachFile:
    def test_is_registered(self) -> None:
        assert attach_file in TOOLS

    @respx.mock
    async def test_resolves_the_party_then_posts_the_document(self, client: BackstopClient) -> None:
        route = respx.post(f"{BASE_URL}/documents").mock(
            return_value=_created("documents", _DOC_ID, title="memo.pdf")
        )

        result = tool_model(
            await attach_file(
                ctx_never_elicit(),
                activity=DocumentFileInput(
                    kind="document",
                    search_type="people",
                    party_id=_PARTY_ID,
                    file_name="memo.pdf",
                    content=_CONTENT,
                ),
                resolve_party_query=make_resolve_party_query(client),
                attach_file_command=make_command(client),
                caller=_CALLER,
            ),
            AttachedFileResponse,
        )

        assert result.id == _DOC_ID
        assert result.kind == "document"
        assert route.call_count == 1

    @respx.mock
    async def test_an_unresolved_search_is_not_found(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=collection())
        )
        respx.get(f"{BASE_URL}/people").mock(return_value=httpx.Response(200, json=collection()))
        route = respx.post(f"{BASE_URL}/documents").mock(
            return_value=_created("documents", _DOC_ID)
        )

        result = tool_model_union(
            await attach_file(
                ctx_never_elicit(),
                activity=DocumentFileInput(
                    kind="document",
                    search_type="people",
                    search="Nobody",
                    file_name="memo.pdf",
                    content=_CONTENT,
                ),
                resolve_party_query=make_resolve_party_query(client),
                attach_file_command=make_command(client),
                caller=_CALLER,
            ),
            AttachedFileResponse | NotFoundResponse,
        )

        assert isinstance(result, NotFoundResponse)
        assert result.query == "Nobody"
        assert result.scope == "people"
        assert route.call_count == 0
