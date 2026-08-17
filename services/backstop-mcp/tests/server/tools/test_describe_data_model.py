"""`describe_data_model`: entities, include names, stage vocabulary, tool ownership."""

from collections.abc import Callable

import httpx
import pytest
import respx

from backstop_mcp.server.instructions import INSTRUCTIONS
from backstop_mcp.server.tools.describe_data_model import (
    DescribeDataModelResponse,
    describe_data_model,
)
from backstop_mcp.server.tools.registry import TOOLS
from tests.features.opportunities.test_fetch import VOCABULARY
from tests.features.party_resolver.helpers import BASE_URL, resource
from tests.server.tools.helpers import tool_model

type ConnectUser = Callable[..., object]


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


class TestDescribeDataModel:
    @pytest.mark.asyncio
    @respx.mock
    async def test_renders_entities_ownership_and_stages(self, connect_user: ConnectUser) -> None:
        await connect_user("user-ddm-1", "ddm-bob")  # pyright: ignore[reportGeneralTypeIssues]
        respx.get(f"{BASE_URL}/opportunity-stages").mock(return_value=_stages_response())

        result = tool_model(await describe_data_model(), DescribeDataModelResponse)

        names = [entity.name for entity in result.entities]
        assert "ContactEmail" in names
        assert "Opportunity" in names
        email = next(entity for entity in result.entities if entity.name == "ContactEmail")
        assert any("retired" in field.name for field in email.fields)
        assert "get_person include=email_addresses" in email.produced_by
        concerns = {entry.concern: entry.tools for entry in result.ownership}
        assert concerns["contact details"] == ("get_person", "get_organization")
        assert concerns["pipeline"] == ("get_opportunities",)
        assert [stage.name for stage in result.stages] == [
            "Prospect",
            "Project",
            "IDD",
            "Client Approval",
            "Execution",
            "Invested",
            "Closed",
        ]

    def test_is_registered(self) -> None:
        assert describe_data_model in TOOLS


class TestInstructions:
    def test_point_at_describe_data_model_and_the_ownership_map(self) -> None:
        assert "describe_data_model" in INSTRUCTIONS
        assert "get_opportunities" in INSTRUCTIONS
        assert "get_activity_history" in INSTRUCTIONS
        assert "representative" in INSTRUCTIONS
