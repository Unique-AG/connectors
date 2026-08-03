import httpx
import pytest
import respx
from fastmcp.server.elicitation import AcceptedElicitation
from mcp.shared.exceptions import McpError
from mcp.types import METHOD_NOT_FOUND, ClientCapabilities, ErrorData

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.party_resolver import NeedsDisambiguation, Resolved, resolve_party
from backstop_mcp.party_resolver.disambiguate import disambiguate_party
from backstop_mcp.party_resolver.types import PartyCandidate
from tests.party_resolver.helpers import (
    BASE_URL,
    FakeContext,
    as_context,
    collection,
    ctx_accept,
    ctx_cancel,
    ctx_decline,
    ctx_unsupported,
    resource,
)


def _two_org_hits() -> dict[str, object]:
    return collection(
        resource("o1", "organizations", name="Capstone A"),
        resource("o2", "organizations", name="Capstone B"),
    )


class TestDisambiguateElicit:
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
        assert result.party.id == "o2"
        assert result.party.name == "Capstone B"

    @pytest.mark.asyncio
    @respx.mock
    async def test_elicit_decline_returns_needs_disambiguation(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=_two_org_hits())
        )

        result = await resolve_party(
            ctx_decline(),
            client,
            search_type="organizations",
            search="Capstone",
        )

        assert isinstance(result, NeedsDisambiguation)
        assert [c.id for c in result.candidates] == ["o1", "o2"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_elicit_cancel_returns_needs_disambiguation(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=_two_org_hits())
        )

        result = await resolve_party(
            ctx_cancel(),
            client,
            search_type="organizations",
            search="Capstone",
        )

        assert isinstance(result, NeedsDisambiguation)
        assert len(result.candidates) == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_elicit_unsupported_returns_needs_disambiguation(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=_two_org_hits())
        )

        result = await resolve_party(
            ctx_unsupported(),
            client,
            search_type="organizations",
            search="Capstone",
        )

        assert isinstance(result, NeedsDisambiguation)
        assert result.search == "Capstone"
        assert result.search_type == "organizations"

    @pytest.mark.asyncio
    async def test_elicit_method_not_found_returns_needs_disambiguation(self) -> None:
        elicit_calls = 0

        async def elicit(*, message: str, response_type: object) -> object:
            nonlocal elicit_calls
            elicit_calls += 1
            _ = message, response_type
            raise McpError(ErrorData(code=METHOD_NOT_FOUND, message="Method not found"))

        candidates = (
            PartyCandidate(id="o1", name="A", label="A"),
            PartyCandidate(id="o2", name="B", label="B"),
        )
        result = await disambiguate_party(
            as_context(FakeContext(elicit)),
            candidates=candidates,
            search="Capstone",
            search_type="organizations",
        )

        assert isinstance(result, NeedsDisambiguation)
        assert elicit_calls == 1
        assert [c.id for c in result.candidates] == ["o1", "o2"]

    @pytest.mark.asyncio
    async def test_missing_elicitation_capability_skips_elicit(self) -> None:
        elicit_calls = 0
        capability_checks: list[ClientCapabilities] = []

        async def elicit(*, message: str, response_type: object) -> object:
            nonlocal elicit_calls
            elicit_calls += 1
            _ = message, response_type
            raise AssertionError("elicit must not be called")

        class _NoElicitSession:
            def check_client_capability(self, capability: ClientCapabilities) -> bool:
                capability_checks.append(capability)
                return False

        fake = FakeContext(elicit)
        object.__setattr__(fake, "session", _NoElicitSession())

        candidates = (
            PartyCandidate(id="o1", name="A", label="A"),
            PartyCandidate(id="o2", name="B", label="B"),
        )
        result = await disambiguate_party(
            as_context(fake),
            candidates=candidates,
            search="Capstone",
            search_type="organizations",
        )

        assert isinstance(result, NeedsDisambiguation)
        assert elicit_calls == 0
        assert [c.id for c in result.candidates] == ["o1", "o2"]
        assert len(capability_checks) == 1
        assert capability_checks[0].elicitation is not None

    @pytest.mark.asyncio
    async def test_capability_check_error_still_attempts_elicit(self) -> None:
        async def elicit(*, message: str, response_type: object) -> AcceptedElicitation[str]:
            _ = message, response_type
            return AcceptedElicitation(data="A")

        class _BrokenSession:
            def check_client_capability(self, capability: ClientCapabilities) -> bool:
                _ = capability
                raise RuntimeError("client session is in a weird state")

        fake = FakeContext(elicit)
        object.__setattr__(fake, "session", _BrokenSession())

        candidates = (
            PartyCandidate(id="o1", name="A", label="A"),
            PartyCandidate(id="o2", name="B", label="B"),
        )
        result = await disambiguate_party(
            as_context(fake),
            candidates=candidates,
            search="Capstone",
            search_type="organizations",
        )

        assert isinstance(result, Resolved)
        assert result.party.id == "o1"

    @pytest.mark.skip(
        reason="Manual spike: Unique MCP client elicit interop (UN-23676); not runnable in CI"
    )
    def test_unique_client_elicit_interop_spike() -> None:
        """Manual: against Unique chat client, ambiguous get_organization search should either
        elicit an enum or degrade to needs_disambiguation candidates — never crash the tool.
        FastMCP 3.x signals unsupported via missing elicitation capability and/or
        McpError METHOD_NOT_FOUND.
        """

    @pytest.mark.asyncio
    async def test_duplicate_labels_are_made_unique_for_elicit(self) -> None:
        candidates = (
            PartyCandidate(id="o1", name="Acme", label="Acme"),
            PartyCandidate(id="o2", name="Acme", label="Acme"),
        )
        captured: dict[str, object] = {}

        async def elicit(*, message: str, response_type: object) -> AcceptedElicitation[str]:
            captured["message"] = message
            captured["response_type"] = response_type
            return AcceptedElicitation(data="Acme [o2]")

        result = await disambiguate_party(
            as_context(FakeContext(elicit)),
            candidates=candidates,
            search="Acme",
            search_type="organizations",
        )

        assert isinstance(result, Resolved)
        assert result.party.id == "o2"
        assert captured["response_type"] == ["Acme", "Acme [o2]"]
