"""`RunReportQuery`: one GET /reports page, flattened to columns and rows."""

from datetime import date

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.reports import RunReportResponse
from tests.features.reports.conftest import make_run_report_query
from tests.helpers import BASE_URL, recorded_params

_REPORT_NAME = "2026 DRF Australia Registrants"
_AS_OF = date(2026, 8, 31)
_REPORTS_URL = f"{BASE_URL}/reports"


def _column(name: str, title: str | None = None) -> dict[str, object]:
    return {"name": name, "title": title if title is not None else name}


def _report_page(
    *rows: dict[str, object],
    header: list[dict[str, object]] | None = None,
    total: int | None = 15,
    extra_values: list[object] | None = None,
    extra_resources: list[dict[str, object]] | None = None,
) -> httpx.Response:
    values: list[object] = list(rows)
    if extra_values is not None:
        values.extend(extra_values)
    resource: dict[str, object] = {
        "id": "152638191",
        "type": "reports",
        "attributes": {
            "result": {
                "header": header
                if header is not None
                else [_column("Email"), _column("Company Name")],
                "values": values,
            }
        },
        "links": "{ }",
    }
    data = [resource, *(extra_resources or ())]
    return httpx.Response(
        200,
        json={
            "data": data,
            "included": [],
            "links": {"next": f"{_REPORTS_URL}?page[offset]=3"},
            "meta": {"totalResourceCount": total},
        },
    )


def _empty_page(*, total: int = 0) -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": [], "included": [], "links": {}, "meta": {"totalResourceCount": total}},
    )


async def _run(
    client: BackstopClient,
    *,
    limit: int = 3,
    offset: int = 0,
    as_of_date: date = _AS_OF,
    report_name: str = _REPORT_NAME,
) -> RunReportResponse:
    return await make_run_report_query(client).run(
        report_name=report_name,
        as_of_date=as_of_date,
        limit=limit,
        offset=offset,
    )


class TestRunReportQuery:
    @pytest.mark.asyncio
    @respx.mock
    async def test_projects_columns_and_rows_from_one_page(self, client: BackstopClient) -> None:
        route = respx.get(_REPORTS_URL).mock(
            return_value=_report_page(
                {
                    "Email": "bruce@btiadvisory.com",
                    "Company Name": "BTI Advisory",
                },
                {
                    "Email": "jessie.wu@cbussuper.com.au",
                    "Company Name": "CBUS",
                },
            )
        )

        result = await _run(client)

        assert route.call_count == 1
        params = recorded_params(route)[0]
        assert params["filter[reportName][eq]"] == _REPORT_NAME
        assert params["filter[asOfDate][eq]"] == "2026-08-31"
        assert params["page[limit]"] == "3"
        assert params["page[offset]"] == "0"
        assert "filter[reportDefinition][eq]" not in params
        assert "filter[restrictionExpression][eq]" not in params
        assert "filter[showHiddenColumns][eq]" not in params
        assert result.report_name == _REPORT_NAME
        assert result.as_of_date == _AS_OF
        assert [(column.name, column.title) for column in result.columns] == [
            ("Email", "Email"),
            ("Company Name", "Company Name"),
        ]
        assert result.rows == (
            {"Email": "bruce@btiadvisory.com", "Company Name": "BTI Advisory"},
            {"Email": "jessie.wu@cbussuper.com.au", "Company Name": "CBUS"},
        )
        assert result.row_count == 2
        assert result.total == 15
        assert result.offset == 0
        assert result.next_offset == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_omits_next_offset_on_the_last_page(self, client: BackstopClient) -> None:
        respx.get(_REPORTS_URL).mock(
            return_value=_report_page(
                {"Email": "last@example.com", "Company Name": "Last"},
                total=15,
            )
        )

        result = await _run(client, limit=3, offset=14)

        assert result.offset == 14
        assert result.row_count == 1
        assert result.total == 15
        assert result.next_offset is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_empty_data_returns_no_rows(self, client: BackstopClient) -> None:
        respx.get(_REPORTS_URL).mock(return_value=_empty_page())

        result = await _run(client)

        assert result.columns == ()
        assert result.rows == ()
        assert result.row_count == 0
        assert result.total == 0
        assert result.next_offset is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_drops_a_value_that_is_not_a_row_object(self, client: BackstopClient) -> None:
        respx.get(_REPORTS_URL).mock(
            return_value=_report_page(
                {"Email": "ok@example.com", "Company Name": "Ok"},
                extra_values=["not-a-row"],
            )
        )

        result = await _run(client)

        assert result.row_count == 1
        assert result.rows == ({"Email": "ok@example.com", "Company Name": "Ok"},)

    @pytest.mark.asyncio
    @respx.mock
    async def test_drops_a_header_with_no_name_or_title(self, client: BackstopClient) -> None:
        respx.get(_REPORTS_URL).mock(
            return_value=_report_page(
                {"Email": "ok@example.com"},
                header=[{"name": "Email", "title": "Email"}, {}],
            )
        )

        result = await _run(client)

        assert [column.name for column in result.columns] == ["Email"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_flattens_values_from_every_data_item(self, client: BackstopClient) -> None:
        second: dict[str, object] = {
            "id": "638901382",
            "type": "reports",
            "attributes": {
                "result": {
                    "header": [_column("Email")],
                    "values": [{"Email": "second@example.com"}],
                }
            },
        }
        respx.get(_REPORTS_URL).mock(
            return_value=_report_page(
                {"Email": "first@example.com"},
                extra_resources=[second],
            )
        )

        result = await _run(client)

        assert [row["Email"] for row in result.rows] == [
            "first@example.com",
            "second@example.com",
        ]

    @pytest.mark.asyncio
    @respx.mock
    async def test_does_not_follow_links_next(self, client: BackstopClient) -> None:
        route = respx.get(_REPORTS_URL).mock(
            return_value=_report_page({"Email": "one@example.com"})
        )

        await _run(client)

        assert route.call_count == 1
