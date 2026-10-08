"""`RunReportQuery`: one GET /reports page, flattened to columns and rows."""

import asyncio
from datetime import date

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopApiError, BackstopClient
from backstop_mcp.features.reports import RunReportPendingResponse, RunReportResponse
from tests.features.reports.conftest import make_run_report_query
from tests.helpers import BASE_URL, recorded_params

_REPORT_NAME = "Quarterly Registrants"
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
    result = await make_run_report_query(client).run(
        report_name=report_name,
        as_of_date=as_of_date,
        limit=limit,
        offset=offset,
    )
    assert isinstance(result, RunReportResponse)
    return result


class _ColdBuild:
    """A respx side effect that answers only once released — a cold report build.

    Counts requests as they start: respx records a call only after its side effect returns,
    so a build that is cancelled while held never shows up in `route.call_count`.
    """

    def __init__(self, response: httpx.Response) -> None:
        self.release: asyncio.Event = asyncio.Event()
        self.started: int = 0
        self._response: httpx.Response = response

    async def __call__(self, _request: httpx.Request) -> httpx.Response:
        self.started += 1
        await self.release.wait()
        return self._response


class TestRunReportQuery:
    @pytest.mark.asyncio
    @respx.mock
    async def test_projects_columns_and_rows_from_one_page(self, client: BackstopClient) -> None:
        route = respx.get(_REPORTS_URL).mock(
            return_value=_report_page(
                {
                    "Email": "first@example.com",
                    "Company Name": "Example Advisory",
                },
                {
                    "Email": "second@example.com",
                    "Company Name": "Example Super",
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
        assert result.columns == ("Email", "Company Name")
        assert result.rows == (
            ("first@example.com", "Example Advisory"),
            ("second@example.com", "Example Super"),
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
        assert result.rows == (("ok@example.com", "Ok"),)

    @pytest.mark.asyncio
    @respx.mock
    async def test_next_offset_counts_dropped_values_so_paging_does_not_repeat(
        self, client: BackstopClient
    ) -> None:
        respx.get(_REPORTS_URL).mock(
            return_value=_report_page(
                {"Email": "ok@example.com"},
                extra_values=["not-a-row"],
                total=15,
            )
        )

        result = await _run(client, limit=2, offset=0)

        # Backstop sent two values and we kept one; the next page starts after both, not
        # after the single readable row, which would re-request the dropped value's slot.
        assert result.row_count == 1
        assert result.next_offset == 2

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

        assert result.columns == ("Email",)

    @pytest.mark.asyncio
    @respx.mock
    async def test_publishes_titles_and_places_cells_by_header_key(
        self, client: BackstopClient
    ) -> None:
        respx.get(_REPORTS_URL).mock(
            return_value=_report_page(
                {"Company Name": "Example Advisory", "email_key": "first@example.com"},
                header=[_column("email_key", "Email"), _column("Company Name")],
            )
        )

        result = await _run(client)

        assert result.columns == ("Email", "Company Name")
        assert result.rows == (("first@example.com", "Example Advisory"),)

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_missing_cell_is_null(self, client: BackstopClient) -> None:
        respx.get(_REPORTS_URL).mock(return_value=_report_page({"Email": "ok@example.com"}))

        result = await _run(client)

        assert result.rows == (("ok@example.com", None),)

    @pytest.mark.asyncio
    @respx.mock
    async def test_keeps_a_cell_the_header_did_not_list(self, client: BackstopClient) -> None:
        respx.get(_REPORTS_URL).mock(
            return_value=_report_page(
                {"Email": "ok@example.com", "Company Name": "Ok", "Region": "EMEA"},
            )
        )

        result = await _run(client)

        assert result.columns == ("Email", "Company Name", "Region")
        assert result.rows == (("ok@example.com", "Ok", "EMEA"),)

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

        assert [row[0] for row in result.rows] == [
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


class TestRunReportQueryColdBuild:
    @pytest.mark.asyncio
    @respx.mock
    async def test_a_slow_build_is_pending_then_collected_without_a_second_request(
        self, client: BackstopClient
    ) -> None:
        build = _ColdBuild(_report_page({"Email": "one@example.com"}))
        respx.get(_REPORTS_URL).mock(side_effect=build)
        query = make_run_report_query(client, wait_seconds=0.05)

        pending = await query.run(report_name=_REPORT_NAME, as_of_date=_AS_OF, limit=3, offset=0)
        build.release.set()
        collected = await query.run(report_name=_REPORT_NAME, as_of_date=_AS_OF, limit=3, offset=0)

        assert pending == RunReportPendingResponse(
            report_name=_REPORT_NAME,
            as_of_date=_AS_OF,
            limit=3,
            offset=0,
            running_seconds=0,
        )
        assert isinstance(collected, RunReportResponse)
        assert collected.rows == (("one@example.com", None),)
        assert build.started == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_collected_run_is_not_served_again(self, client: BackstopClient) -> None:
        route = respx.get(_REPORTS_URL).mock(return_value=_report_page())
        query = make_run_report_query(client)

        await query.run(report_name=_REPORT_NAME, as_of_date=_AS_OF, limit=3, offset=0)
        await query.run(report_name=_REPORT_NAME, as_of_date=_AS_OF, limit=3, offset=0)

        assert route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_other_pages_are_separate_runs(self, client: BackstopClient) -> None:
        build = _ColdBuild(_report_page({"Email": "one@example.com"}))
        route = respx.get(_REPORTS_URL).mock(side_effect=build)
        query = make_run_report_query(client, wait_seconds=0.05)

        first = await query.run(report_name=_REPORT_NAME, as_of_date=_AS_OF, limit=3, offset=0)
        second = await query.run(report_name=_REPORT_NAME, as_of_date=_AS_OF, limit=3, offset=3)
        build.release.set()
        page = await query.run(report_name=_REPORT_NAME, as_of_date=_AS_OF, limit=3, offset=3)
        await query.run(report_name=_REPORT_NAME, as_of_date=_AS_OF, limit=3, offset=0)

        assert isinstance(first, RunReportPendingResponse)
        assert isinstance(second, RunReportPendingResponse)
        assert isinstance(page, RunReportResponse)
        assert page.offset == 3
        assert build.started == 2
        assert sorted(params["page[offset]"] for params in recorded_params(route)) == ["0", "3"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_other_dates_are_separate_runs(self, client: BackstopClient) -> None:
        build = _ColdBuild(_report_page())
        respx.get(_REPORTS_URL).mock(side_effect=build)
        query = make_run_report_query(client, wait_seconds=0.05)
        other_date = date(2026, 9, 30)

        await query.run(report_name=_REPORT_NAME, as_of_date=_AS_OF, limit=3, offset=0)
        await query.run(report_name=_REPORT_NAME, as_of_date=other_date, limit=3, offset=0)
        build.release.set()
        await query.run(report_name=_REPORT_NAME, as_of_date=_AS_OF, limit=3, offset=0)
        await query.run(report_name=_REPORT_NAME, as_of_date=other_date, limit=3, offset=0)

        assert build.started == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_an_expired_run_is_cancelled_and_started_again(
        self, client: BackstopClient
    ) -> None:
        build = _ColdBuild(_report_page())
        route = respx.get(_REPORTS_URL).mock(side_effect=build)
        query = make_run_report_query(client, wait_seconds=0.05, ttl_seconds=0)

        await query.run(report_name=_REPORT_NAME, as_of_date=_AS_OF, limit=3, offset=0)
        await query.run(report_name=_REPORT_NAME, as_of_date=_AS_OF, limit=3, offset=0)
        build.release.set()
        await asyncio.sleep(0.05)

        assert build.started == 2
        # The expired build was cancelled, so only the second one ever answered.
        assert route.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_full_cache_cancels_the_oldest_run(self, client: BackstopClient) -> None:
        build = _ColdBuild(_report_page())
        route = respx.get(_REPORTS_URL).mock(side_effect=build)
        query = make_run_report_query(client, wait_seconds=0.05, cache_size=1)

        await query.run(report_name=_REPORT_NAME, as_of_date=_AS_OF, limit=3, offset=0)
        await query.run(report_name=_REPORT_NAME, as_of_date=_AS_OF, limit=3, offset=3)
        build.release.set()
        collected = await query.run(report_name=_REPORT_NAME, as_of_date=_AS_OF, limit=3, offset=3)
        restarted = await query.run(report_name=_REPORT_NAME, as_of_date=_AS_OF, limit=3, offset=0)

        assert isinstance(collected, RunReportResponse)
        assert isinstance(restarted, RunReportResponse)
        # Offset 0 was evicted while held, so it never answered and had to be sent again.
        assert build.started == 3
        assert route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_run_evicted_while_a_call_waits_is_started_over(
        self, client: BackstopClient
    ) -> None:
        build = _ColdBuild(_report_page())
        respx.get(_REPORTS_URL).mock(side_effect=build)
        query = make_run_report_query(client, wait_seconds=0.2, cache_size=1)

        waiting = asyncio.create_task(
            query.run(report_name=_REPORT_NAME, as_of_date=_AS_OF, limit=3, offset=0)
        )
        await asyncio.sleep(0.05)
        await query.run(report_name=_REPORT_NAME, as_of_date=_AS_OF, limit=3, offset=3)
        evicted = await waiting
        build.release.set()
        await asyncio.sleep(0.05)

        # The waiting call's run was cancelled by the eviction; it answers pending, not
        # CancelledError, and starts a new run for the next call to collect.
        assert isinstance(evicted, RunReportPendingResponse)
        assert build.started >= 3

    @pytest.mark.asyncio
    @respx.mock
    async def test_two_calls_waiting_on_an_evicted_run_share_one_replacement(
        self, client: BackstopClient
    ) -> None:
        build = _ColdBuild(_report_page())
        respx.get(_REPORTS_URL).mock(side_effect=build)
        query = make_run_report_query(client, wait_seconds=0.2, cache_size=1)

        waiting = [
            asyncio.create_task(
                query.run(report_name=_REPORT_NAME, as_of_date=_AS_OF, limit=3, offset=0)
            )
            for _ in range(2)
        ]
        await asyncio.sleep(0.05)
        await query.run(report_name=_REPORT_NAME, as_of_date=_AS_OF, limit=3, offset=3)
        results = await asyncio.gather(*waiting)
        build.release.set()
        await asyncio.sleep(0.05)

        # The second waiter joins the replacement the first one started instead of failing.
        assert all(isinstance(result, RunReportPendingResponse) for result in results)

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_failed_run_raises_to_the_collector_and_is_dropped(
        self, client: BackstopClient
    ) -> None:
        build = _ColdBuild(httpx.Response(400, json={"errors": [{"detail": "Report X not found"}]}))
        respx.get(_REPORTS_URL).mock(side_effect=build)
        query = make_run_report_query(client, wait_seconds=0.05)

        await query.run(report_name=_REPORT_NAME, as_of_date=_AS_OF, limit=3, offset=0)
        build.release.set()
        with pytest.raises(BackstopApiError):
            await query.run(report_name=_REPORT_NAME, as_of_date=_AS_OF, limit=3, offset=0)
        with pytest.raises(BackstopApiError):
            await query.run(report_name=_REPORT_NAME, as_of_date=_AS_OF, limit=3, offset=0)

        assert build.started == 2
