import logging
from datetime import date

import httpx
import pytest
import respx
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from backstop_mcp.backstop_client import BackstopApiError
from backstop_mcp.features.reports import (
    DEFAULT_REPORT_PAGE_SIZE,
    RunReportResponse,
)
from backstop_mcp.features.reports.tools.run_report import run_report
from backstop_mcp.features.resolution import NotFoundResponse
from backstop_mcp.observability import tool_call_scope
from backstop_mcp.server.tools import TOOLS
from backstop_mcp.utils import identifiable_value
from tests.features.reports.conftest import make_run_report_query
from tests.helpers import (
    BASE_URL,
    SERVICE_LOGGER,
    assert_canary_absent,
    recorded_params,
    tool_client,
)
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
            "columns": ["Email", "Company Name"],
            "rows": [["first@example.com", "Example Advisory"]],
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


@pytest.mark.usefixtures("keyed_pseudonyms")
class TestRunReportToolTelemetry:
    @pytest.mark.asyncio
    @respx.mock
    async def test_tool_call_fields_and_spans_carry_the_keyed_report_name(
        self, caplog: pytest.LogCaptureFixture, exporter: InMemorySpanExporter
    ) -> None:
        base_url = tenant("rr-telemetry")
        report_name = "zq-canary-report-tool"
        respx.get(f"{base_url}/reports").mock(
            return_value=_page({"Email": report_name, "Company Name": report_name})
        )

        with (
            caplog.at_level(logging.DEBUG, logger=SERVICE_LOGGER),
            trace.get_tracer(__name__).start_as_current_span("tools/call run_report"),
            tool_call_scope() as call,
        ):
            async with tool_client(base_url) as client:
                await run_report(
                    report_name=report_name,
                    as_of_date=_AS_OF,
                    run_report_query=make_run_report_query(client),
                )

        pseudonym = str(identifiable_value(report_name))
        assert pseudonym.startswith("hmac-sha256:")
        assert str(call.fields["report_name"]) == pseudonym
        spans_with_report_name = [
            span
            for span in exporter.get_finished_spans()
            if span.attributes is not None and "report_name" in span.attributes
        ]
        assert spans_with_report_name
        for span in spans_with_report_name:
            assert span.attributes is not None
            assert span.attributes["report_name"] == pseudonym, span.name
        assert_canary_absent(caplog, exporter, report_name)
