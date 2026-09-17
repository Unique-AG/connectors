from datetime import date

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopApiError
from backstop_mcp.features.reports import (
    DEFAULT_REPORT_PAGE_SIZE,
    RunReportResponse,
)
from backstop_mcp.features.reports.tools.run_report import run_report
from backstop_mcp.features.resolution import NotFoundResponse
from backstop_mcp.server.tools import TOOLS
from tests.features.reports.conftest import make_run_report_query
from tests.helpers import BASE_URL, recorded_params, tool_client
from tests.server.tools.helpers import tool_model, tool_payload

_REPORT_NAME = "Quarterly Registrants"
_AS_OF = date(2026, 8, 31)


def tenant(name: str) -> str:
    return f"{BASE_URL}/{name}"


def _page(
    *rows: dict[str, object],
    total: int = 15,
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": [
                {
                    "id": "152638191",
                    "type": "reports",
                    "attributes": {
                        "result": {
                            "header": [
                                {"name": "Email", "title": "Email"},
                                {"name": "Company Name", "title": "Company Name"},
                            ],
                            "values": list(rows),
                        }
                    },
                }
            ],
            "included": [],
            "links": {},
            "meta": {"totalResourceCount": total},
        },
    )


class TestRunReportTool:
    def test_is_registered(self) -> None:
        assert run_report in TOOLS

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_one_page_for_a_named_report(self) -> None:
        base_url = tenant("rr-page")
        route = respx.get(f"{base_url}/reports").mock(
            return_value=_page(
                {"Email": "first@example.com", "Company Name": "Example Advisory"},
            )
        )

        async with tool_client(base_url) as client:
            result = tool_model(
                await run_report(
                    report_name=_REPORT_NAME,
                    as_of_date=_AS_OF,
                    limit=3,
                    offset=0,
                    run_report_query=make_run_report_query(client),
                ),
                RunReportResponse,
            )

        assert route.call_count == 1
        params = recorded_params(route)[0]
        assert params["filter[reportName][eq]"] == _REPORT_NAME
        assert params["filter[asOfDate][eq]"] == "2026-08-31"
        assert params["page[limit]"] == "3"
        assert params["page[offset]"] == "0"
        assert tool_payload(result) == {
            "report_name": _REPORT_NAME,
            "as_of_date": "2026-08-31",
            "columns": [
                {"name": "Email", "title": "Email"},
                {"name": "Company Name", "title": "Company Name"},
            ],
            "rows": [{"Email": "first@example.com", "Company Name": "Example Advisory"}],
            "row_count": 1,
            "total": 15,
            "offset": 0,
            "next_offset": 1,
        }

    @pytest.mark.asyncio
    @respx.mock
    async def test_defaults_as_of_date_to_today_and_first_page(self) -> None:
        base_url = tenant("rr-defaults")
        route = respx.get(f"{base_url}/reports").mock(return_value=_page())

        async with tool_client(base_url) as client:
            result = tool_model(
                await run_report(
                    report_name=_REPORT_NAME,
                    run_report_query=make_run_report_query(client),
                ),
                RunReportResponse,
            )

        params = recorded_params(route)[0]
        assert params["filter[asOfDate][eq]"] == date.today().isoformat()
        assert params["page[limit]"] == str(DEFAULT_REPORT_PAGE_SIZE)
        assert params["page[offset]"] == "0"
        assert result.as_of_date == date.today()
        assert result.offset == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_unknown_report_name_is_not_found(self) -> None:
        base_url = tenant("rr-missing")
        respx.get(f"{base_url}/reports").mock(
            return_value=httpx.Response(
                400,
                json={
                    "errors": [
                        {
                            "code": "InvalidParameterException",
                            "title": "Report 'zzz-does-not-exist' not found.",
                        }
                    ]
                },
            )
        )

        async with tool_client(base_url) as client:
            result = tool_model(
                await run_report(
                    report_name="zzz-does-not-exist",
                    as_of_date=_AS_OF,
                    run_report_query=make_run_report_query(client),
                ),
                NotFoundResponse,
            )

        assert result.query == "zzz-does-not-exist"
        assert result.scope == "reports"

    @pytest.mark.asyncio
    @respx.mock
    async def test_other_bad_request_stays_an_error(self) -> None:
        base_url = tenant("rr-bad")
        respx.get(f"{base_url}/reports").mock(
            return_value=httpx.Response(
                400,
                json={
                    "errors": [
                        {
                            "code": "InvalidParameterException",
                            "title": "Either a reportDefinition or a reportName is required.",
                        }
                    ]
                },
            )
        )

        async with tool_client(base_url) as client:
            with pytest.raises(BackstopApiError) as exc_info:
                await run_report(
                    report_name=_REPORT_NAME,
                    as_of_date=_AS_OF,
                    run_report_query=make_run_report_query(client),
                )

        assert exc_info.value.status_code == 400
        assert "reportDefinition" in exc_info.value.detail
