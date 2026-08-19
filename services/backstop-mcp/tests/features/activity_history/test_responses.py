"""`to_timeline_record`: the pure conversion from a fetched item to its wire shape.

Each test targets one behaviour from the design doc's "Token budget" section: an activity
record's gist/truncation/`description_length` wiring, email recipient capping (both under- and
over-the-cap cases) and the count field's presence/absence, the `occurred_at` type distinction
(date for activities, datetime for email), and a record with no description producing an empty
gist rather than an error.
"""

from datetime import UTC, date, datetime

from backstop_mcp.features.activity_history import (
    ActivityGroupResponse,
    ActivityHistoryResolvedResponse,
    ActivityItem,
    ActivityRecordResponse,
    EmailItem,
    EmailRecordResponse,
    ResolvedPartyAsOfResponse,
    resolved_party_as_of_response,
    to_timeline_record,
)
from backstop_mcp.features.activity_history.fetch_activities import BackstopActivityType
from backstop_mcp.features.data_hygiene import AsOfResponse, ProvenanceAttributes
from backstop_mcp.features.party_resolver import ResolvedParty

_DEFAULT_ACTIVITY_DATE = date(2026, 1, 15)
_DEFAULT_EMAIL_TIMESTAMP = datetime(2026, 1, 15, 9, 30, tzinfo=UTC)


def _activity_item(
    *,
    item_id: str = "meeting-or-calls_1",
    stream: BackstopActivityType = "meeting",
    title: str | None = "Q1 review",
    description: str | None = "<p>hello</p>",
    effective_date: date | None = _DEFAULT_ACTIVITY_DATE,
    resource_id: str | None = "76280387",
) -> ActivityItem:
    return ActivityItem(
        id=item_id,
        stream=stream,
        title=title,
        description=description,
        effective_date=effective_date,
        resource_type="meeting-or-calls",
        resource_id=resource_id,
        created_timestamp=None,
        modified_timestamp=None,
    )


def _email_item(
    *,
    item_id: str = "email_1",
    subject: str | None = "Re: proposal",
    sent_timestamp: datetime | None = _DEFAULT_EMAIL_TIMESTAMP,
    from_email: str | None = "sender@example.com",
    to_emails: tuple[str, ...] = ("a@example.com",),
    cc_emails: tuple[str, ...] = (),
    has_attachments: bool | None = False,
) -> EmailItem:
    return EmailItem(
        id=item_id,
        subject=subject,
        sent_timestamp=sent_timestamp,
        from_email=from_email,
        to_emails=to_emails,
        cc_emails=cc_emails,
        has_attachments=has_attachments,
        content_url=None,
    )


class TestActivityRecord:
    def test_untruncated_gist_omits_description_length(self) -> None:
        item = _activity_item(description="<p>short body</p>")
        record = to_timeline_record(item, gist_max_chars=300)

        assert isinstance(record, ActivityRecordResponse)
        assert record.gist == "short body"
        assert record.gist_truncated is False
        assert record.description_length is None

    def test_truncated_gist_reports_full_length(self) -> None:
        body = "word " * 200
        item = _activity_item(description=f"<p>{body}</p>")
        record = to_timeline_record(item, gist_max_chars=20)

        assert isinstance(record, ActivityRecordResponse)
        assert record.gist_truncated is True
        assert record.description_length == len(body.strip())
        assert len(record.gist or "") <= 20

    def test_no_description_yields_empty_gist_not_an_error(self) -> None:
        item = _activity_item(description=None)
        record = to_timeline_record(item, gist_max_chars=300)

        assert isinstance(record, ActivityRecordResponse)
        assert record.gist == ""
        assert record.gist_truncated is False
        assert record.description_length is None

    def test_occurred_at_is_a_plain_date(self) -> None:
        item = _activity_item(effective_date=date(2026, 3, 4))
        record = to_timeline_record(item, gist_max_chars=300)

        assert isinstance(record, ActivityRecordResponse)
        assert record.occurred_at == date(2026, 3, 4)

    def test_carries_type_activity_id_and_resource_id(self) -> None:
        item = _activity_item(item_id="meeting-or-calls_76280387", resource_id="76280387")
        record = to_timeline_record(item, gist_max_chars=300)

        assert isinstance(record, ActivityRecordResponse)
        assert record.type == "meeting"
        assert record.activity_id == "meeting-or-calls_76280387"
        assert record.resource_id == "76280387"


class TestEmailRecord:
    def test_recipient_list_under_cap_has_no_count(self) -> None:
        item = _email_item(to_emails=("a@example.com", "b@example.com"))
        record = to_timeline_record(item, gist_max_chars=300)

        assert isinstance(record, EmailRecordResponse)
        assert record.to_emails == ("a@example.com", "b@example.com")
        assert record.to_emails_count is None

    def test_recipient_list_over_cap_is_truncated_with_count(self) -> None:
        addresses = tuple(f"user{i}@example.com" for i in range(5))
        item = _email_item(to_emails=addresses, cc_emails=addresses)
        record = to_timeline_record(item, gist_max_chars=300)

        assert isinstance(record, EmailRecordResponse)
        assert record.to_emails == addresses[:3]
        assert record.to_emails_count == 5
        assert record.cc_emails == addresses[:3]
        assert record.cc_emails_count == 5

    def test_occurred_at_is_a_full_timestamp(self) -> None:
        sent = datetime(2026, 3, 4, 8, 15, tzinfo=UTC)
        item = _email_item(sent_timestamp=sent)
        record = to_timeline_record(item, gist_max_chars=300)

        assert isinstance(record, EmailRecordResponse)
        assert record.occurred_at == sent

    def test_carries_type_email_and_activity_id(self) -> None:
        item = _email_item(item_id="email_42")
        record = to_timeline_record(item, gist_max_chars=300)

        assert isinstance(record, EmailRecordResponse)
        assert record.type == "email"
        assert record.activity_id == "email_42"


class TestActivityHistoryResolvedResponse:
    def test_accepts_groups_and_has_no_flat_records_or_cursor(self) -> None:
        record = to_timeline_record(_activity_item(), gist_max_chars=300)
        group = ActivityGroupResponse(
            activity_type="meeting",
            items=(record,),
            date_range=None,
            next=None,
        )
        response = ActivityHistoryResolvedResponse(
            resolved=ResolvedPartyAsOfResponse(id="1", search_type="people", name="Ada"),
            groups={"meeting": group},
        )

        assert response.groups["meeting"].items == (record,)
        assert not hasattr(response, "records")
        assert not hasattr(response, "next_cursor")
        assert not hasattr(response, "employments")
        assert not hasattr(response, "as_of")

    def test_merges_party_identity_and_as_of(self) -> None:
        resolved = resolved_party_as_of_response(
            ResolvedParty(id="1", search_type="people", name="Ada"),
            ProvenanceAttributes.model_validate(
                {"modifiedTimestamp": "2024-01-01", "modifiedBy": "alice"}
            ),
        )

        assert resolved == ResolvedPartyAsOfResponse(
            id="1",
            search_type="people",
            name="Ada",
            as_of=AsOfResponse(modified_timestamp="2024-01-01", modified_by="alice"),
        )
