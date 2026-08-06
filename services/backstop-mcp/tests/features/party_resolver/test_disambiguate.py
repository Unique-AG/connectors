import httpx
import pytest
import respx
from fastmcp.server.elicitation import AcceptedElicitation
from mcp.shared.exceptions import McpError
from mcp.types import METHOD_NOT_FOUND, ClientCapabilities, ErrorData

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.party_resolver import ResolvedParty, resolve_party
from backstop_mcp.features.resolution import Ambiguous, Candidate, Resolved, elicit_choice
from tests.features.party_resolver.helpers import (
    BASE_URL,
    FakeContext,
    as_context,
    collection,
    ctx_accept,
    ctx_cancel,
    ctx_decline,
    ctx_no_elicitation_capability,
    ctx_unsupported,
    resource,
)


def _two_org_hits() -> dict[str, object]:
    return collection(
        resource("o1", "organizations", name="Capstone A"),
        resource("o2", "organizations", name="Capstone B"),
    )


def _candidate(party_id: str, label: str) -> Candidate[ResolvedParty]:
    return Candidate(
        key=party_id,
        label=label,
        value=ResolvedParty(id=party_id, type="organizations", name=label),
    )


def _ambiguous(*candidates: Candidate[ResolvedParty]) -> Ambiguous[ResolvedParty]:
    return Ambiguous(query="Capstone", scope="organizations", candidates=candidates)


class TestDisambiguateElicit:
    """Both resolvers share one ambiguity policy, so it is tested once, on `elicit_choice`."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_elicit_accept_resolves_selected_candidate(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=_two_org_hits())
        )

        result = await resolve_party(
            ctx_accept("Capstone B"),
            client,
            search_type="organizations",
            search="Capstone",
        )

        assert isinstance(result, Resolved)
        assert result.value.id == "o2"
        assert result.value.name == "Capstone B"

    @pytest.mark.asyncio
    @respx.mock
    async def test_elicit_decline_returns_ambiguous(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=_two_org_hits())
        )

        result = await resolve_party(
            ctx_decline(),
            client,
            search_type="organizations",
            search="Capstone",
        )

        assert isinstance(result, Ambiguous)
        assert [c.value.id for c in result.candidates] == ["o1", "o2"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_elicit_cancel_returns_ambiguous(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=_two_org_hits())
        )

        result = await resolve_party(
            ctx_cancel(),
            client,
            search_type="organizations",
            search="Capstone",
        )

        assert isinstance(result, Ambiguous)
        assert len(result.candidates) == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_elicit_raising_returns_ambiguous(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=_two_org_hits())
        )

        result = await resolve_party(
            ctx_unsupported(),
            client,
            search_type="organizations",
            search="Capstone",
        )

        assert isinstance(result, Ambiguous)
        assert result.query == "Capstone"
        assert result.scope == "organizations"

    @pytest.mark.asyncio
    async def test_elicit_method_not_found_returns_ambiguous(self) -> None:
        """One documented way a client signals it can't elicit (UN-23676's spike question)."""
        elicit_calls = 0

        async def elicit(*, message: str, response_type: object) -> object:
            nonlocal elicit_calls
            elicit_calls += 1
            _ = message, response_type
            raise McpError(ErrorData(code=METHOD_NOT_FOUND, message="Method not found"))

        ambiguous = _ambiguous(_candidate("o1", "A"), _candidate("o2", "B"))
        result = await elicit_choice(
            as_context(FakeContext(elicit)), ambiguous, prompt="Which one?"
        )

        assert result is ambiguous
        assert elicit_calls == 1

    @pytest.mark.asyncio
    async def test_missing_elicitation_capability_skips_elicit(self) -> None:
        """The other way: the client never advertised the capability at initialization."""
        ambiguous = _ambiguous(_candidate("o1", "A"), _candidate("o2", "B"))

        result = await elicit_choice(
            ctx_no_elicitation_capability(), ambiguous, prompt="Which one?"
        )

        assert result is ambiguous

    @pytest.mark.asyncio
    async def test_capability_check_error_degrades_rather_than_guessing(self) -> None:
        """A broken session degrades to the structured payload instead of blind-elicitating.

        Failing toward "hand the candidates to the model" keeps the tool answerable; attempting
        an elicit against a session that can't answer capability questions does not.
        """

        async def elicit(*, message: str, response_type: object) -> AcceptedElicitation[str]:
            _ = message, response_type
            raise AssertionError("elicit must not be attempted")

        class _BrokenSession:
            def check_client_capability(self, capability: ClientCapabilities) -> bool:
                _ = capability
                raise RuntimeError("client session is in a weird state")

        fake = FakeContext(elicit)
        object.__setattr__(fake.request_context, "session", _BrokenSession())

        ambiguous = _ambiguous(_candidate("o1", "A"), _candidate("o2", "B"))
        result = await elicit_choice(as_context(fake), ambiguous, prompt="Which one?")

        assert result is ambiguous

    @pytest.mark.asyncio
    async def test_no_request_context_degrades(self) -> None:
        """Outside a request there is no session to prompt through."""

        class _ContextlessContext:
            request_context: None = None

            async def elicit(self, *, message: str, response_type: object) -> object:
                _ = message, response_type
                raise AssertionError("elicit must not be attempted")

        ambiguous = _ambiguous(_candidate("o1", "A"), _candidate("o2", "B"))
        result = await elicit_choice(
            as_context(_ContextlessContext()),  # pyright: ignore[reportArgumentType]
            ambiguous,
            prompt="Which one?",
        )

        assert result is ambiguous

    @pytest.mark.skip(
        reason="Manual spike: Unique MCP client elicit interop (UN-23676); not runnable in CI"
    )
    def test_unique_client_elicit_interop_spike() -> None:
        """Manual: against Unique chat client, ambiguous get_organization search should either
        elicit an enum or degrade to `ambiguous` candidates — never crash the tool.
        FastMCP 3.x signals unsupported via missing elicitation capability and/or
        McpError METHOD_NOT_FOUND; both paths are covered above.
        """

    @pytest.mark.asyncio
    async def test_duplicate_labels_are_made_unique_for_elicit(self) -> None:
        """An elicit enum needs distinct strings, so colliding labels get their key appended."""
        captured: dict[str, object] = {}

        async def elicit(*, message: str, response_type: object) -> AcceptedElicitation[str]:
            captured["message"] = message
            captured["response_type"] = response_type
            return AcceptedElicitation(data="Acme [o2]")

        ambiguous = _ambiguous(_candidate("o1", "Acme"), _candidate("o2", "Acme"))
        result = await elicit_choice(
            as_context(FakeContext(elicit)), ambiguous, prompt="Which Acme?"
        )

        assert isinstance(result, Resolved)
        assert result.value.id == "o2"
        assert captured["response_type"] == ["Acme", "Acme [o2]"]
        assert captured["message"] == "Which Acme?"

    @pytest.mark.asyncio
    async def test_unrecognized_choice_degrades(self) -> None:
        async def elicit(*, message: str, response_type: object) -> AcceptedElicitation[str]:
            _ = message, response_type
            return AcceptedElicitation(data="Something Else Entirely")

        ambiguous = _ambiguous(_candidate("o1", "A"), _candidate("o2", "B"))
        result = await elicit_choice(
            as_context(FakeContext(elicit)), ambiguous, prompt="Which one?"
        )

        assert result is ambiguous
