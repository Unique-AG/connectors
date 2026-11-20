import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.shared.seam import Confirmed
from office_365_mcp.tools.outlook_draft_reply_all import draft_reply_all

_MAILBOX = "support@example.com"
_MESSAGE_ID = "AAMkAGI2SYNTHETIC-original-0001="
_MESSAGE_REF = "outlook:///messages/AAMkAGI2SYNTHETIC-original-0001%3D"
_ORIGINAL_PATH = "/users/support%40example.com/messages/AAMkAGI2SYNTHETIC-original-0001%3D"
_LOOKALIKE = "jordan@example.com"


def _original() -> dict[str, object]:
    return {
        "id": _MESSAGE_ID,
        "subject": "Q3 plan",
        "from": {"emailAddress": {"name": "Ana", "address": "ana@example.com"}},
        "toRecipients": [{"emailAddress": {"name": _LOOKALIKE}}],
        "ccRecipients": [{"emailAddress": {"name": _LOOKALIKE.upper()}}],
    }


class TestTheQuestionForAnotherMailbox:
    async def test_a_name_with_no_address_does_not_hide_an_address_given_for_cc_or_bcc(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ORIGINAL_PATH).mock(return_value=httpx.Response(200, json=_original()))
        asked: list[str] = []

        async def refusing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return "Nothing was created."

        with pytest.raises(ToolError, match="Nothing was created"):
            _ = await draft_reply_all(
                client,
                message_ref=_MESSAGE_REF,
                body_html="<p>Thanks.</p>",
                confirm=refusing,
                cc=[_LOOKALIKE],
                mailbox=_MAILBOX,
            )

        (question,) = asked
        assert f"It is copied to {_LOOKALIKE.upper()}, {_LOOKALIKE}." in question, question
        assert "That is 4 addresses in all." in question, question

    async def test_the_mailbox_in_the_original_does_not_hide_it_as_an_added_bcc(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        original = {
            **_original(),
            "toRecipients": [{"emailAddress": {"name": "Support", "address": _MAILBOX}}],
        }
        _ = graph.get(_ORIGINAL_PATH).mock(return_value=httpx.Response(200, json=original))
        asked: list[str] = []

        async def refusing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return "Nothing was created."

        with pytest.raises(ToolError, match="Nothing was created"):
            _ = await draft_reply_all(
                client,
                message_ref=_MESSAGE_REF,
                body_html="<p>Thanks.</p>",
                confirm=refusing,
                bcc=[_MAILBOX.upper()],
                mailbox=_MAILBOX,
            )

        (question,) = asked
        assert f"It is blind copied to {_MAILBOX.upper()}." in question, question
