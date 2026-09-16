"""`delete_activity`: format a confirmation prompt, then delete unless elicitation was declined."""

from collections.abc import AsyncGenerator

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from mcp.types import ElicitRequestFormParams, ElicitResult, InputRequiredResult

from backstop_mcp.backstop_client import BackstopApiError, BackstopClient
from backstop_mcp.features.activity_history import GetActivityDetailQuery
from backstop_mcp.features.activity_writes import (
    DeleteActivityInput,
    DeletedActivityResponse,
    get_delete_activity_command_factory,
)
from backstop_mcp.features.activity_writes.tools.delete_activity import delete_activity
from backstop_mcp.features.elicitation_utils import (
    DELETE,
    DELETION_INPUT_KEY,
    KEEP,
    DeletionNeedsConfirmationResponse,
)
from backstop_mcp.server.tools import TOOLS
from tests.features.party_resolver.helpers import (
    ctx_deletion_answer,
    ctx_handshake_era,
    ctx_never_elicit,
    ctx_no_elicitation_capability,
)
from tests.helpers import BASE_URL, client_factory, credential
from tests.server.tools.helpers import tool_model

_NOTE_ID = "76280387"
_EMAIL_ID = "77001122"


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def _detail_document(resource_id: str, **attributes: object) -> dict[str, object]:
    return {
        "data": {
            "type": "entity-activity-details",
            "id": resource_id,
            "attributes": attributes,
        }
    }


class TestDeleteActivity:
    def test_is_registered(self) -> None:
        assert delete_activity in TOOLS

    @respx.mock
    async def test_deletes_when_the_client_cannot_elicit(self, client: BackstopClient) -> None:
        details = respx.get(f"{BASE_URL}/entity-activity-details/{_NOTE_ID}").mock(
            return_value=httpx.Response(
                200,
                json=_detail_document(_NOTE_ID, type="note", title="Follow up"),
            )
        )
        route = respx.delete(f"{BASE_URL}/notes/{_NOTE_ID}").mock(return_value=httpx.Response(204))

        result = tool_model(
            await delete_activity(
                ctx_no_elicitation_capability(),
                activity=DeleteActivityInput(kind="note", activity_id=_NOTE_ID),
                get_activity_detail_query=GetActivityDetailQuery(client=client),
                delete_activity_command=get_delete_activity_command_factory(client),
            ),
            DeletedActivityResponse,
        )

        assert result.id == _NOTE_ID
        assert result.resource_type == "notes"
        assert result.permanent is True
        assert details.call_count == 0
        assert route.call_count == 1

    @respx.mock
    async def test_reads_the_activity_then_asks_without_deleting(
        self, client: BackstopClient
    ) -> None:
        details = respx.get(f"{BASE_URL}/entity-activity-details/{_NOTE_ID}").mock(
            return_value=httpx.Response(
                200,
                json=_detail_document(
                    _NOTE_ID,
                    type="note",
                    title="Follow-up note",
                    description="<p>Called about renewal.</p>",
                ),
            )
        )
        route = respx.delete(f"{BASE_URL}/notes/{_NOTE_ID}").mock(return_value=httpx.Response(204))

        result = await delete_activity(
            ctx_never_elicit(),
            activity=DeleteActivityInput(kind="note", activity_id=_NOTE_ID),
            get_activity_detail_query=GetActivityDetailQuery(client=client),
            delete_activity_command=get_delete_activity_command_factory(client),
        )

        assert isinstance(result, InputRequiredResult)
        assert result.input_requests is not None
        params = result.input_requests[DELETION_INPUT_KEY].params
        assert isinstance(params, ElicitRequestFormParams)
        assert "Follow-up note" in params.message
        assert "Called about renewal" in params.message
        assert "no recycle bin" in params.message
        assert details.call_count == 1
        assert route.call_count == 0

    @respx.mock
    async def test_handshake_era_returns_needs_confirmation_without_deleting(
        self, client: BackstopClient
    ) -> None:
        details = respx.get(f"{BASE_URL}/entity-activity-details/{_NOTE_ID}").mock(
            return_value=httpx.Response(
                200,
                json=_detail_document(
                    _NOTE_ID,
                    type="note",
                    title="Follow-up note",
                    description="<p>Called about renewal.</p>",
                ),
            )
        )
        route = respx.delete(f"{BASE_URL}/notes/{_NOTE_ID}").mock(return_value=httpx.Response(204))

        result = tool_model(
            await delete_activity(
                ctx_handshake_era(),
                activity=DeleteActivityInput(kind="note", activity_id=_NOTE_ID),
                get_activity_detail_query=GetActivityDetailQuery(client=client),
                delete_activity_command=get_delete_activity_command_factory(client),
            ),
            DeletionNeedsConfirmationResponse,
        )

        assert result.status == "needs_confirmation"
        assert "Follow-up note" in result.preview
        assert details.call_count == 1
        assert route.call_count == 0

    @respx.mock
    async def test_handshake_era_deletes_when_confirm_is_true(
        self, client: BackstopClient
    ) -> None:
        route = respx.delete(f"{BASE_URL}/notes/{_NOTE_ID}").mock(return_value=httpx.Response(204))

        result = tool_model(
            await delete_activity(
                ctx_handshake_era(),
                activity=DeleteActivityInput(kind="note", activity_id=_NOTE_ID, confirm=True),
                get_activity_detail_query=GetActivityDetailQuery(client=client),
                delete_activity_command=get_delete_activity_command_factory(client),
            ),
            DeletedActivityResponse,
        )

        assert result.id == _NOTE_ID
        assert route.call_count == 1

    @respx.mock
    async def test_elicit_decline_does_not_delete(self, client: BackstopClient) -> None:
        route = respx.delete(f"{BASE_URL}/notes/{_NOTE_ID}").mock(return_value=httpx.Response(204))

        with pytest.raises(ToolError, match="not confirmed"):
            await delete_activity(
                ctx_deletion_answer(ElicitResult(action="decline")),
                activity=DeleteActivityInput(kind="note", activity_id=_NOTE_ID),
                get_activity_detail_query=GetActivityDetailQuery(client=client),
                delete_activity_command=get_delete_activity_command_factory(client),
            )

        assert route.call_count == 0

    @respx.mock
    async def test_elicit_cancel_does_not_delete(self, client: BackstopClient) -> None:
        route = respx.delete(f"{BASE_URL}/notes/{_NOTE_ID}").mock(return_value=httpx.Response(204))

        with pytest.raises(ToolError, match="not confirmed"):
            await delete_activity(
                ctx_deletion_answer(ElicitResult(action="cancel")),
                activity=DeleteActivityInput(kind="note", activity_id=_NOTE_ID),
                get_activity_detail_query=GetActivityDetailQuery(client=client),
                delete_activity_command=get_delete_activity_command_factory(client),
            )

        assert route.call_count == 0

    @respx.mock
    async def test_choosing_keep_does_not_delete(self, client: BackstopClient) -> None:
        route = respx.delete(f"{BASE_URL}/notes/{_NOTE_ID}").mock(return_value=httpx.Response(204))

        with pytest.raises(ToolError, match="not confirmed"):
            await delete_activity(
                ctx_deletion_answer(ElicitResult(action="accept", content={"choice": KEEP})),
                activity=DeleteActivityInput(kind="note", activity_id=_NOTE_ID),
                get_activity_detail_query=GetActivityDetailQuery(client=client),
                delete_activity_command=get_delete_activity_command_factory(client),
            )

        assert route.call_count == 0

    @respx.mock
    async def test_missing_note_404_does_not_delete(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/entity-activity-details/{_NOTE_ID}").mock(
            return_value=httpx.Response(200, json={"data": None})
        )
        route = respx.delete(f"{BASE_URL}/notes/{_NOTE_ID}").mock(return_value=httpx.Response(204))

        with pytest.raises(BackstopApiError) as raised:
            await delete_activity(
                ctx_never_elicit(),
                activity=DeleteActivityInput(kind="note", activity_id=_NOTE_ID),
                get_activity_detail_query=GetActivityDetailQuery(client=client),
                delete_activity_command=get_delete_activity_command_factory(client),
            )

        assert raised.value.status_code == 404
        assert route.call_count == 0

    @respx.mock
    async def test_email_history_handle_elicits_without_detail_then_deletes(
        self, client: BackstopClient
    ) -> None:
        details = respx.get(url__regex=r".*/entity-activity-details/.*").mock(
            return_value=httpx.Response(200, json=_detail_document(_EMAIL_ID))
        )
        route = respx.delete(f"{BASE_URL}/emails/{_EMAIL_ID}").mock(
            return_value=httpx.Response(204)
        )
        ask = await delete_activity(
            ctx_never_elicit(),
            activity=DeleteActivityInput(kind="email", activity_id=f"emails_{_EMAIL_ID}"),
            get_activity_detail_query=GetActivityDetailQuery(client=client),
            delete_activity_command=get_delete_activity_command_factory(client),
        )

        assert isinstance(ask, InputRequiredResult)
        assert ask.input_requests is not None
        params = ask.input_requests[DELETION_INPUT_KEY].params
        assert isinstance(params, ElicitRequestFormParams)
        assert _EMAIL_ID in params.message
        assert "email" in params.message
        assert details.call_count == 0
        assert route.call_count == 0

        result = tool_model(
            await delete_activity(
                ctx_deletion_answer(ElicitResult(action="accept", content={"choice": DELETE})),
                activity=DeleteActivityInput(kind="email", activity_id=f"emails_{_EMAIL_ID}"),
                get_activity_detail_query=GetActivityDetailQuery(client=client),
                delete_activity_command=get_delete_activity_command_factory(client),
            ),
            DeletedActivityResponse,
        )

        assert result.id == _EMAIL_ID
        assert result.resource_type == "emails"
        assert details.call_count == 0
        assert route.call_count == 1
