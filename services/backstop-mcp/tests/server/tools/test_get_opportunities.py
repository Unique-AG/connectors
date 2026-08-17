"""`get_opportunities`: party resolution, concurrent fetch, status filter, no cursor."""

from collections.abc import Callable
from typing import cast

import httpx
import pytest
import respx
from fastmcp.decorators import get_fastmcp_meta
from fastmcp.tools.function_tool import ToolMeta

from backstop_mcp.backstop_client import BackstopApiError
from backstop_mcp.features.resolution import NotFoundResponse
from backstop_mcp.server.tools.get_opportunities import (
    GetOpportunitiesResponse,
    OpportunitiesResolvedResponse,
    get_opportunities,
    search_type_for,
)
from backstop_mcp.server.tools.registry import TOOLS
from tests.features.opportunities.test_fetch import VOCABULARY
from tests.features.party_resolver.helpers import (
    BASE_URL,
    collection,
    ctx_decline,
    ctx_never_elicit,
    resource,
)
from tests.server.tools.helpers import object_dict, tool_model, tool_model_union, tool_payload

type ConnectUser = Callable[..., object]

_ORG_ID = "341764767"
_OPPORTUNITIES_URL = f"{BASE_URL}/organizations/{_ORG_ID}/opportunities"
_STAGES_URL = f"{BASE_URL}/opportunity-stages"
_PEOPLE_OPPORTUNITIES_URL = f"{BASE_URL}/people/p9/opportunities"


def _opportunity(
    opportunity_id: str, *, stage_id: str | None = None, **attributes: object
) -> dict[str, object]:
    relationships: dict[str, object] = {"stageHistory": {"data": []}}
    if stage_id is not None:
        relationships["stage"] = {"data": {"id": stage_id, "type": "opportunity-stages"}}
    return {
        "id": opportunity_id,
        "type": "opportunities",
        "attributes": attributes,
        "relationships": relationships,
    }


def _page(
    *resources: dict[str, object], included: list[dict[str, object]] | None = None
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": list(resources),
            "included": included or [],
            "links": {"next": None},
        },
    )


def _side_loaded_stage(stage_id: str) -> dict[str, object]:
    known = VOCABULARY[stage_id]
    return resource(
        stage_id,
        "opportunity-stages",
        name=known.name,
        sortOrder=known.sort_order,
        closed=known.closed,
    )


def _stages_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": [
                resource(
                    stage.id,
                    "opportunity-stages",
                    name=stage.name,
                    sortOrder=stage.sort_order,
                    closed=stage.closed,
                )
                for stage in VOCABULARY.values()
            ],
            "links": {"next": None},
        },
    )


def _open_deal() -> dict[str, object]:
    return _opportunity(
        "5755031",
        stage_id="42482",
        name="Koch - CATS Select",
        isOpen=True,
        previousStage="Client Approval",
        dateEnteredCurrentStage="2026-03-01T00:00:00.000-0500",
    )


def _closed_deal() -> dict[str, object]:
    return _opportunity(
        "5072909",
        stage_id="96016",
        name="Koch - Invested",
        isOpen=False,
        dateEnteredCurrentStage="2024-11-13T00:00:00.000-0500",
    )


class TestGetOpportunities:
    @pytest.mark.asyncio
    @respx.mock
    async def test_trusted_party_id_returns_the_pipeline(self, connect_user: ConnectUser) -> None:
        await connect_user("user-opp-1", "opp-bob")  # pyright: ignore[reportGeneralTypeIssues]

        stages = respx.get(_STAGES_URL).mock(return_value=_stages_response())
        opportunities = respx.get(_OPPORTUNITIES_URL).mock(
            return_value=_page(_open_deal(), included=[_side_loaded_stage("42482")])
        )

        result = tool_model(
            await get_opportunities(
                ctx_never_elicit(), party_type="organization", party_id=_ORG_ID
            ),
            OpportunitiesResolvedResponse,
        )

        assert stages.call_count == 1
        assert opportunities.call_count == 1
        assert result.resolved.id == _ORG_ID
        assert result.resolved.search_type == "organizations"
        assert result.total == 1
        assert result.open_count == 1
        assert result.closed_count == 0
        assert result.opportunities[0].stage == "IDD"
        assert result.opportunities[0].previous_stage == "Client Approval"

    @pytest.mark.asyncio
    @respx.mock
    async def test_unique_search_resolves_then_fetches(self, connect_user: ConnectUser) -> None:
        await connect_user("user-opp-2", "opp-carol")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json=collection(resource(_ORG_ID, "organizations", name="Koch")),
            )
        )
        respx.get(_STAGES_URL).mock(return_value=_stages_response())
        respx.get(_OPPORTUNITIES_URL).mock(
            return_value=_page(_open_deal(), included=[_side_loaded_stage("42482")])
        )

        result = tool_model(
            await get_opportunities(ctx_never_elicit(), party_type="organization", search="Koch"),
            OpportunitiesResolvedResponse,
        )

        assert result.resolved.name == "Koch"
        assert result.opportunities[0].name == "Koch - CATS Select"

    @pytest.mark.asyncio
    @respx.mock
    async def test_person_party_hits_the_people_sub_collection(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-opp-3", "opp-dave")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(_STAGES_URL).mock(return_value=_stages_response())
        people_opps = respx.get(_PEOPLE_OPPORTUNITIES_URL).mock(
            return_value=_page(_open_deal(), included=[_side_loaded_stage("42482")])
        )

        result = tool_model(
            await get_opportunities(ctx_never_elicit(), party_type="person", party_id="p9"),
            OpportunitiesResolvedResponse,
        )

        assert people_opps.call_count == 1
        assert result.resolved.search_type == "people"

    @pytest.mark.asyncio
    @respx.mock
    async def test_status_open_still_reports_the_closed_count(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-opp-4", "opp-erin")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(_STAGES_URL).mock(return_value=_stages_response())
        respx.get(_OPPORTUNITIES_URL).mock(
            return_value=_page(
                _open_deal(),
                _closed_deal(),
                included=[_side_loaded_stage("42482"), _side_loaded_stage("96016")],
            )
        )

        result = tool_model(
            await get_opportunities(
                ctx_never_elicit(),
                party_type="organization",
                party_id=_ORG_ID,
                status="open",
            ),
            OpportunitiesResolvedResponse,
        )

        assert [deal.id for deal in result.opportunities] == ["5755031"]
        assert result.total == 2
        assert result.open_count == 1
        assert result.closed_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_deal_that_has_never_moved_omits_previous_stage(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-opp-5", "opp-frank")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(_STAGES_URL).mock(return_value=_stages_response())
        respx.get(_OPPORTUNITIES_URL).mock(
            return_value=_page(
                _opportunity(
                    "1",
                    stage_id="42478",
                    name="Never moved",
                    isOpen=True,
                    dateEnteredCurrentStage="2026-01-01T00:00:00.000-0500",
                ),
                included=[_side_loaded_stage("42478")],
            )
        )

        payload = tool_payload(
            await get_opportunities(ctx_never_elicit(), party_type="organization", party_id=_ORG_ID)
        )

        deals = payload["opportunities"]
        assert isinstance(deals, list)
        assert deals
        first = object_dict(cast(object, deals[0]))
        assert "previous_stage" not in first
        assert first["stage"] == "Prospect"

    @pytest.mark.asyncio
    @respx.mock
    async def test_not_found_search_returns_the_query(self, connect_user: ConnectUser) -> None:
        await connect_user("user-opp-6", "opp-gina")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=collection())
        )

        result = tool_model_union(
            await get_opportunities(
                ctx_never_elicit(), party_type="organization", search="NoSuchOrg"
            ),
            GetOpportunitiesResponse,
        )

        assert isinstance(result, NotFoundResponse)
        assert result.query == "NoSuchOrg"

    @pytest.mark.asyncio
    @respx.mock
    async def test_ambiguous_search_returns_candidates(self, connect_user: ConnectUser) -> None:
        await connect_user("user-opp-7", "opp-hank")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json=collection(
                    resource("o1", "organizations", name="Koch"),
                    resource("o2", "organizations", name="Koch Investments"),
                ),
            )
        )

        result = tool_model_union(
            await get_opportunities(ctx_decline(), party_type="organization", search="Koch"),
            GetOpportunitiesResponse,
        )

        dumped = object_dict(cast(object, result.model_dump(mode="json")))
        assert dumped["status"] == "ambiguous"
        candidates = dumped["candidates"]
        assert isinstance(candidates, list)
        assert len(cast("list[object]", candidates)) == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_failed_stages_fetch_fails_the_call(self, connect_user: ConnectUser) -> None:
        await connect_user("user-opp-8", "opp-ivy")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(_STAGES_URL).mock(return_value=httpx.Response(500, json={"errors": []}))
        respx.get(_OPPORTUNITIES_URL).mock(
            return_value=_page(_open_deal(), included=[_side_loaded_stage("42482")])
        )

        with pytest.raises(BackstopApiError):
            await get_opportunities(ctx_never_elicit(), party_type="organization", party_id=_ORG_ID)

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_failed_opportunities_fetch_fails_the_call(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-opp-9", "opp-jade")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(_STAGES_URL).mock(return_value=_stages_response())
        respx.get(_OPPORTUNITIES_URL).mock(return_value=httpx.Response(500, json={"errors": []}))

        with pytest.raises(BackstopApiError):
            await get_opportunities(ctx_never_elicit(), party_type="organization", party_id=_ORG_ID)

    def test_docstring_says_there_is_no_cursor_and_names_previous_stage(self) -> None:
        doc = get_opportunities.__doc__
        assert doc is not None
        assert "no cursor" in doc.lower()
        assert "LEFT" in doc
        assert "vocabulary" in doc.lower()

    def test_is_registered(self) -> None:
        assert get_opportunities in TOOLS

    def test_output_schema_documents_previous_stage(self) -> None:
        meta = get_fastmcp_meta(get_opportunities)
        assert isinstance(meta, ToolMeta)
        schema = meta.output_schema
        assert schema is not None
        dumped = str(schema)
        assert "previous_stage" in dumped
        assert "LEFT" in dumped
        assert "Omitted until the deal has moved" in dumped
        assert "Omitted when this instance no longer publishes" in dumped


class TestSearchTypeFor:
    def test_defaults_from_party_type(self) -> None:
        assert search_type_for("organization", None) == "organizations"
        assert search_type_for("person", None) == "people"

    def test_rejects_a_mismatch(self) -> None:
        with pytest.raises(ValueError, match="organizations"):
            search_type_for("organization", "people")
        with pytest.raises(ValueError, match="organizations"):
            search_type_for("person", "organizations")

    def test_allows_a_person_contact_echo(self) -> None:
        assert search_type_for("person", "contacts") == "contacts"
