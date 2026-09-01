"""The recorded shape of `GET /v3/investors/{id}`, parsed and projected.

Structure taken verbatim from a live response; every value replaced. Two fields here are the
reason this file exists — the spec declares `consultants` an array and the API sends an
index-keyed object, and declares `asset_allocation_breakdown` an object and sends a list — so
conformance against the spec alone would have passed while the tool crashed.
"""

import json
import pathlib
from typing import cast

import pytest

from with_intelligence_mcp.features.investors import (
    InvestorExtendedAttributes,
    InvestorProfileResponse,
    project_investor,
)

_RECORDING = pathlib.Path(__file__).parent / "recordings" / "investor-extended.json"


@pytest.fixture(scope="module")
def record() -> InvestorExtendedAttributes:
    body = cast("dict[str, object]", json.loads(_RECORDING.read_text()))
    return InvestorExtendedAttributes.model_validate(body)


@pytest.fixture(scope="module")
def projected(record: InvestorExtendedAttributes) -> InvestorProfileResponse:
    return project_investor(record)


class TestParsingTheRecordedShape:
    def test_the_whole_record_parses(self, record: InvestorExtendedAttributes) -> None:
        assert record.id == 2504
        assert record.name == "Example Retirement System (ERS)"

    def test_consultants_arrive_as_an_index_keyed_object(
        self, record: InvestorExtendedAttributes
    ) -> None:
        """Declared `array<InvestorConsultant>`; delivered `{"0": {...}, "1": {...}}`."""
        assert [c.name for c in record.consultants] == ["Consultant One", "Consultant Two"]
        assert record.consultants[0].is_lead is True

    def test_fields_we_do_not_model_are_ignored(self, record: InvestorExtendedAttributes) -> None:
        """`asset_allocation_breakdown`, `service_providers`, `investment_industries` and the
        `_shape` note all pass through without breaking parsing."""
        assert record.contacts_total == 64


class TestWhatTheToolPublishes:
    def test_aum_is_labelled_as_millions_with_the_vendors_own_band(
        self, projected: InvestorProfileResponse
    ) -> None:
        """135900 is $135.9bn. Publishing it as a bare `value` invites a 6-orders-of-magnitude
        misreading, which is why the field says millions and carries the band."""
        assert projected.aum is not None
        assert projected.aum.value_millions == 135900
        assert projected.aum.value_usd_millions == 135900
        assert projected.aum.band == "> $50bn"
        assert projected.aum.currency == "USD"
        assert projected.aum.as_of == "2026-08-07T00:00:00"

    def test_the_summary_is_markdown_not_html(self, projected: InvestorProfileResponse) -> None:
        assert projected.summary is not None
        assert "<p>" not in projected.summary
        assert "***Example Retirement System (Defined Contribution)***" in projected.summary

    def test_strategies_are_grouped_under_their_primary(
        self, projected: InvestorProfileResponse
    ) -> None:
        grouped = {group.primary: group.secondary for group in projected.strategies}
        assert grouped == {"Equity": ["Long/Short Equity"], "Multi-Strategy": []}

    def test_the_lead_consultant_is_identifiable(self, projected: InvestorProfileResponse) -> None:
        leads = [c.name for c in projected.consultants if c.is_lead]
        assert leads == ["Consultant One"]

    def test_location_reads_from_the_nested_objects(
        self, projected: InvestorProfileResponse
    ) -> None:
        assert projected.location == "Exampleville, Example State, United States"

    def test_contacts_are_ids_and_the_total_says_how_many_exist(
        self, projected: InvestorProfileResponse
    ) -> None:
        assert projected.contact_ids == [650889, 471270, 779796]
        assert projected.contacts_total == 64

    def test_managers_keep_their_ids_including_negative_ones(
        self, projected: InvestorProfileResponse
    ) -> None:
        """Manager ids are signed in the live data; treating them as unsigned would drop rows."""
        assert [m.id for m in projected.managers] == [2145858758, -179975042]

    def test_preferences_are_reported_unavailable_on_this_subscription(
        self, projected: InvestorProfileResponse
    ) -> None:
        """The recorded record carries no `preferences`, which is what an account without the
        Intentions & Preferences add-on sees."""
        assert projected.preferences_available is False
        assert projected.preferences is None
