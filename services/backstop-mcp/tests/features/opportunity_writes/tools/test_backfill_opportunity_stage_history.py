"""`backfill_opportunity_stage_history`: registered and wired through the command factory."""

from collections.abc import AsyncGenerator
from datetime import date

import httpx
import pytest
import respx
from pydantic import TypeAdapter

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.opportunity_writes import (
    BackfillOpportunityStageHistoryCommand,
    BackfillOpportunityStageHistoryInput,
    BackfillOpportunityStageHistoryResponse,
    get_backfill_opportunity_stage_history_command_factory,
)
from backstop_mcp.features.opportunity_writes.tools.backfill_opportunity_stage_history import (
    backfill_opportunity_stage_history,
)
from backstop_mcp.server.tools import TOOLS
from tests.helpers import (
    BASE_URL,
    client_factory,
    credential,
    opportunity_stages_service,
    recorded_json_bodies,
    resource,
)
from tests.server.tools.helpers import object_dict, object_list, tool_model

_BACKFILL: TypeAdapter[BackfillOpportunityStageHistoryInput] = TypeAdapter(
    BackfillOpportunityStageHistoryInput
)
_IDD = "42482"


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def make_command(client: BackstopClient) -> BackfillOpportunityStageHistoryCommand:
    return get_backfill_opportunity_stage_history_command_factory(
        client,
        opportunity_stages_service=opportunity_stages_service(client),
    )


class TestBackfillOpportunityStageHistory:
    def test_is_registered(self) -> None:
        assert backfill_opportunity_stage_history in TOOLS

    @respx.mock
    async def test_posts_the_history_row(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/opportunity-stages").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [resource(_IDD, "opportunity-stages", name="IDD", closed=False)],
                    "links": {"next": None},
                },
            )
        )
        respx.get(f"{BASE_URL}/opportunities/5755101").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "id": "5755101",
                        "type": "opportunities",
                        "attributes": {},
                        "relationships": {},
                    }
                },
            )
        )
        route = respx.post(f"{BASE_URL}/bulk-opportunity-stage-history").mock(
            return_value=httpx.Response(
                201,
                json={
                    "data": {
                        "id": None,
                        "type": "bulk-opportunity-stage-history",
                        "attributes": {
                            "records": [
                                {
                                    "id": "1789380940322",
                                    "effectiveDate": "2026-02-01T00:00:00.000-0400",
                                    "opportunity": {
                                        "resourceType": "opportunities",
                                        "resourceId": "5755101",
                                    },
                                    "stage": {
                                        "resourceType": "opportunity-stages",
                                        "resourceId": _IDD,
                                    },
                                }
                            ],
                            "bulkLoadSummary": {
                                "totalCount": 1,
                                "successCount": 1,
                                "errorMessages": [],
                            },
                        },
                        "links": "{ }",
                    },
                    "included": [],
                },
            )
        )

        result = tool_model(
            await backfill_opportunity_stage_history(
                backfill=_BACKFILL.validate_python(
                    {
                        "records": [
                            {
                                "opportunity_id": "5755101",
                                "stage": "IDD",
                                "effective_date": date(2026, 2, 1),
                            }
                        ]
                    }
                ),
                backfill_opportunity_stage_history_command=make_command(client),
            ),
            BackfillOpportunityStageHistoryResponse,
        )

        assert result.total_count == 1
        assert result.applied_count == 1
        assert result.records[0].status == "applied"
        body = recorded_json_bodies(route)[0]
        row = object_dict(
            object_list(object_dict(object_dict(body["data"])["attributes"])["records"])[0]
        )
        assert object_dict(row["opportunity"]) == {
            "resourceId": "5755101",
            "resourceType": "opportunities",
        }
