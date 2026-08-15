"""What a model is told when Graph says no.

These assertions are about *advice*, not wording: each one pins the fact that distinguishes one
remedy from another, because getting those wrong is what makes a model retry a call that can never
succeed, or give up on one that would have worked a second later.
"""

import pytest
from fastmcp.exceptions import ToolError

from office_mcp.graph_client import (
    GraphFailure,
    GraphForbidden,
    GraphNotFound,
    GraphPagingUnending,
    GraphThrottled,
    GraphUnavailable,
)
from office_mcp.shared.seam import entra_token_errors, graph_tool_errors

_PERMISSION = "Chat.Read"
_CHANNELS = "ChannelMessage.Read.All"

# What azure-identity's `OnBehalfOfCredential.get_token` reports when the delegated permission was
# never consented to, trimmed of its trace ids.
_UNCONSENTED = (
    "AADSTS65001: The user or administrator has not consented to use the application with ID "
    + "'1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061'. Send an interactive authorization request for "
    + "this user and resource."
)


def _message(failure: GraphFailure) -> str:
    with pytest.raises(ToolError) as raised, graph_tool_errors(_PERMISSION):
        raise failure
    return str(raised.value)


def _token_message(failure: Exception) -> str:
    with pytest.raises(ToolError) as raised, entra_token_errors(_PERMISSION):
        raise failure
    return str(raised.value)


class TestTheTwoRemediesGraphCannotTellApart:
    """401 and 403 are both `GraphForbidden`. One is fixed by the user, the other by an admin."""

    def test_a_rejected_token_asks_the_user_to_sign_in_again(self) -> None:
        message = _message(
            GraphForbidden("nope", status=401, code="InvalidAuthenticationToken", request_id=None)
        )

        assert "sign in" in message
        assert _PERMISSION not in message, "a 401 is not a missing-permission problem"

    def test_a_missing_permission_names_the_permission_and_who_must_grant_it(self) -> None:
        """The failure Graph is least helpful about: it never says which permission was missing,
        so the tool has to. Without the name, the remedy is not actionable."""
        message = _message(
            GraphForbidden("nope", status=403, code="Authorization_RequestDenied", request_id=None)
        )

        assert message.count(_PERMISSION) >= 1
        assert "administrator" in message
        assert "Retrying will not help" in message

    def test_the_transcript_tenant_switch_is_neither_of_those_and_says_so(self) -> None:
        """A third remedy behind the same status and the same outer code, and the one that is not
        a permission at all: Graph access to Teams meeting transcripts is a tenant-wide Teams
        setting, off by default, that no app can turn on. Naming a permission here would send an
        administrator after one that was never missing, and telling the user to sign in again would
        cost a re-consent that changes nothing — so the remedy names the Teams admin centre and the
        cmdlet, and rules re-consent out in as many words.
        """
        message = _message(
            GraphForbidden(
                "nope",
                status=403,
                code="Forbidden",
                request_id=None,
                inner_code="GraphAccessToTranscriptsDisabled",
            )
        )

        assert "Teams administrator" in message
        assert "Set-CsTeamsMeetingConfiguration" in message
        assert "sign in again will not change it" in message
        assert _PERMISSION not in message, (
            "no permission is missing, and naming one sends an administrator after nothing"
        )

    def test_an_ordinary_403_is_still_about_a_permission(self) -> None:
        """The negative control: recognition is by inner code and never by status alone, or every
        missing permission would be reported as a tenant setting nobody has switched off."""
        message = _message(
            GraphForbidden("nope", status=403, code="Forbidden", request_id=None, inner_code="Foo")
        )

        assert _PERMISSION in message
        assert "Teams administrator" not in message


class TestRetryAdvice:
    def test_throttling_passes_graphs_own_delay_through(self) -> None:
        """Graph's `Retry-After` is the documented fastest way out of throttling; an eager retry
        makes it last longer, so the number has to survive into the message."""
        message = _message(
            GraphThrottled(
                "slow down",
                status=429,
                code="activityLimitReached",
                request_id=None,
                retry_after_seconds=42.0,
            )
        )

        assert "42 seconds" in message

    def test_throttling_without_a_delay_still_says_not_to_spin(self) -> None:
        message = _message(
            GraphThrottled(
                "slow down", status=429, code=None, request_id=None, retry_after_seconds=None
            )
        )

        assert "loop" in message
        assert "seconds" not in message, "no invented number when Graph gave no advice"

    def test_an_outage_is_worth_exactly_one_retry(self) -> None:
        message = _message(GraphUnavailable("boom", status=503, code=None, request_id=None))

        assert "Retry once" in message

    def test_a_collection_graph_will_not_end_reaches_the_caller_as_advice(self) -> None:
        """The one failure here that no request produced: Graph answering page after empty page
        while still advertising more, which `collect_pages` refuses. It is a `GraphFailure` so that
        it arrives the way a 429 or a 403 does — as a tool error a model can act on — and the count
        has to survive into the message, because it is the only evidence there is.
        """
        message = _message(
            GraphPagingUnending("11 empty pages in a row, and Graph says more", empty_pages=11)
        )

        assert "11 pages in a row" in message
        assert "nothing in them" in message
        assert "no other arguments will avoid it" in message, "not a bad-request remedy"
        assert "None" not in message, "no status, no code, nothing invented in their place"

    def test_a_bad_request_is_not_worth_retrying(self) -> None:
        message = _message(GraphFailure("bad filter", status=400, code=None, request_id=None))

        assert "retrying it unchanged will fail identically" in message

    def test_a_missing_item_does_not_claim_the_item_does_not_exist(self) -> None:
        """Graph returns 404 both for "no such thing" and for "none of your business", so a
        message that asserts absence teaches the model something false."""
        message = _message(GraphNotFound("gone", status=404, code=None, request_id=None))

        assert "not allowed to know it exists" in message

    def test_a_tool_whose_id_came_from_another_tool_can_say_so_instead(self) -> None:
        """The default advice — check the id came from a tool response verbatim — is the right
        first guess when a caller supplied an id, and wrong for a handle another tool just
        produced: it sends the model to re-check the one thing that cannot be the cause. Only the
        404 advice is replaceable, because it is the only one whose remedy depends on where the
        argument came from.
        """
        with pytest.raises(ToolError) as raised, graph_tool_errors(_PERMISSION, not_found="Gone."):
            raise GraphNotFound("gone", status=404, code=None, request_id="req-7")

        assert str(raised.value) == "Gone. (HTTP 404, Graph request id req-7)"

    def test_it_does_not_replace_the_advice_for_any_other_failure(self) -> None:
        with pytest.raises(ToolError) as raised, graph_tool_errors(_PERMISSION, not_found="Gone."):
            raise GraphForbidden("nope", status=403, code=None, request_id=None)

        assert "Gone." not in str(raised.value)
        assert _PERMISSION in str(raised.value)


class TestDiagnostics:
    def test_the_graph_request_id_survives(self) -> None:
        """It exists only in that one response, and it is the first thing Microsoft support asks
        for — losing it makes a production failure untraceable afterwards."""
        message = _message(
            GraphUnavailable("boom", status=500, code="internalError", request_id="req-42")
        )

        assert "HTTP 500" in message
        assert "Graph error code internalError" in message
        assert "Graph request id req-42" in message

    def test_nothing_is_invented_when_graph_sent_no_evidence(self) -> None:
        message = _message(GraphUnavailable("unreachable", status=None, code=None, request_id=None))

        assert "None" not in message

    def test_a_success_passes_through_untouched(self) -> None:
        with graph_tool_errors(_PERMISSION):
            outcome = "fine"

        assert outcome == "fine"


class TestTheRefusalThatHappensBeforeGraph:
    """A permission nobody consented to fails in the On-Behalf-Of exchange, not in Graph.

    Same remedy as the 403 above, reached a step earlier — and the step matters, because this one
    happens while FastMCP is resolving the tool's token dependency, where the default report is
    "Failed to resolve dependency 'graph_token'".
    """

    def test_an_unconsented_permission_names_the_permission_and_the_remedy(self) -> None:
        message = _token_message(RuntimeError(_UNCONSENTED))

        assert message.count(_PERMISSION) >= 1
        assert "administrator" in message
        assert "grant the delegated permission" in message
        assert "sign in" in message, "consent granted after sign-in needs a new token"
        assert "retrying will not help" in message.lower()

    def test_it_says_the_call_never_happened(self) -> None:
        """Unlike every Graph failure above, nothing was asked of Microsoft 365 here — a model
        that believes otherwise reports the read as attempted-and-refused."""
        message = _token_message(RuntimeError(_UNCONSENTED))

        assert "never reached Microsoft Graph" in message

    def test_entras_own_code_survives_for_whoever_has_to_diagnose_it(self) -> None:
        message = _token_message(RuntimeError(_UNCONSENTED))

        assert "AADSTS65001" in message
        assert "Send an interactive authorization request" not in message, (
            "the model cannot act on Entra's prose, and it is not addressed to this connector"
        )

    def test_a_failure_entra_never_answered_is_still_actionable(self) -> None:
        """No AADSTS code means the exchange never got as far as Entra — a broken connector, not
        a refused user. The permission is still named, because it is still what was being asked
        for, and the exception type is the only evidence there is."""
        message = _token_message(ValueError("no access token available"))

        assert _PERMISSION in message
        assert "AADSTS" not in message, "no code was invented"
        assert "ValueError" in message

    def test_an_exchange_for_several_permissions_names_them_all(self) -> None:
        """A tool needing two permissions gets one token or none: Entra redeems the scopes together
        and refuses them together, saying no more about which one was unconsented than a Graph 403
        does. Naming one of two would send an administrator to grant a permission that may already
        be there, and the second attempt fails identically."""
        with pytest.raises(ToolError) as raised, entra_token_errors(_PERMISSION, _CHANNELS):
            raise RuntimeError(_UNCONSENTED)
        message = str(raised.value)

        assert _PERMISSION in message
        assert _CHANNELS in message
        assert "grant the delegated permissions" in message, "plural, or it reads as one of them"
        assert "administrator" in message

    def test_a_token_that_arrives_passes_through_untouched(self) -> None:
        with entra_token_errors(_PERMISSION):
            token = "synthetic-obo-graph-token"

        assert token == "synthetic-obo-graph-token"
