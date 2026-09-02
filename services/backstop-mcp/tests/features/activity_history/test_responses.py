"""History records map from wire attributes: gist, recipient cap, and `occurred_at`.

Each test targets one behaviour from the design doc's "Token budget" section: an activity
record's gist/truncation/`description_length` wiring, email recipient capping (both under- and
over-the-cap cases) and the count field's presence/absence, the `occurred_at` type distinction
(date for activities, datetime for email), and a record with no description producing an empty
gist rather than an error.
"""

from datetime import UTC, date, datetime

from backstop_mcp.features.activity_history import (
    ActivityAttributes,
    ActivityGroupResponse,
    ActivityHistoryResolvedResponse,
    ActivityRecordResponse,
    BackstopActivityType,
    EmailAttributes,
    EmailRecordResponse,
    ResolvedPartyAsOfResponse,
    TimelineRecord,
)
from backstop_mcp.features.data_hygiene import AsOfResponse, ProvenanceAttributes
from backstop_mcp.features.party_resolver import ResolvedPartyDto

_DEFAULT_ACTIVITY_DATE = date(2026, 1, 15)
_DEFAULT_EMAIL_TIMESTAMP = datetime(2026, 1, 15, 9, 30, tzinfo=UTC)


def _activity_record(
    *,
    item_id: str = "meeting-or-calls_1",
    stream: BackstopActivityType = "meeting",
    title: str | None = "Q1 review",
    description: str | None = "<p>hello</p>",
    effective_date: date | None = _DEFAULT_ACTIVITY_DATE,
    resource_id: str | None = "76280387",
    gist_max_chars: int = 300,
    regarding: object | None = None,
) -> ActivityRecordResponse:
    return ActivityRecordResponse.from_attributes(
        item_id,
        stream,
        ActivityAttributes.model_validate(
            {
                "title": title,
                "description": description,
                "effectiveDate": effective_date,
                "specificResource": (
                    None
                    if resource_id is None
                    else {"resourceId": resource_id, "resourceType": "meeting-or-calls"}
                ),
                "regarding": regarding,
            }
        ),
        tags=(),
        attendees=(),
        gist_max_chars=gist_max_chars,
    )


def _email_record(
    *,
    item_id: str = "email_1",
    subject: str | None = "Re: proposal",
    sent_timestamp: datetime | None = _DEFAULT_EMAIL_TIMESTAMP,
    from_email: str | None = "sender@example.com",
    to_emails: tuple[str, ...] = ("a@example.com",),
    cc_emails: tuple[str, ...] = (),
    has_attachments: bool | None = False,
) -> EmailRecordResponse:
    return EmailRecordResponse.from_attributes(
        item_id,
        EmailAttributes.model_validate(
            {
                "subject": subject,
                "sentTimestamp": sent_timestamp,
                "fromEmail": from_email,
                "toEmails": list(to_emails),
                "ccEmails": list(cc_emails),
                "hasAttachments": has_attachments,
            }
        ),
    )


class TestActivityRecord:
    def test_untruncated_gist_omits_description_length(self) -> None:
        record = _activity_record(description="<p>short body</p>")

        assert record.gist == "short body"
        assert record.gist_truncated is False
        assert record.description_length is None

    def test_truncated_gist_reports_full_length(self) -> None:
        body = "word " * 200
        record = _activity_record(description=f"<p>{body}</p>", gist_max_chars=20)

        assert record.gist_truncated is True
        assert record.description_length == len(body.strip())
        assert len(record.gist or "") <= 20

    def test_no_description_yields_empty_gist_not_an_error(self) -> None:
        record = _activity_record(description=None)

        assert record.gist == ""
        assert record.gist_truncated is False
        assert record.description_length is None

    def test_occurred_at_is_a_plain_date(self) -> None:
        record = _activity_record(effective_date=date(2026, 3, 4))

        assert record.occurred_at == date(2026, 3, 4)

    def test_carries_type_activity_id_and_resource_id(self) -> None:
        record = _activity_record(item_id="meeting-or-calls_76280387", resource_id="76280387")

        assert record.type == "meeting"
        assert record.activity_id == "meeting-or-calls_76280387"
        assert record.resource_id == "76280387"

    def test_regarding_parses_from_the_stored_ref(self) -> None:
        record = _activity_record(
            regarding={
                "resourceId": "o42",
                "resourceType": "organizations",
                "resourceLink": "/organizations/o42",
            }
        )

        assert record.regarding is not None
        assert record.regarding.id == "o42"
        assert record.regarding.resource_type == "organizations"
        assert record.regarding.search_type == "organizations"

    def test_malformed_regarding_is_omitted(self) -> None:
        record = _activity_record(regarding="not-a-ref")

        assert record.regarding is None


class TestEmailRecord:
    def test_recipient_list_under_cap_has_no_count(self) -> None:
        record = _email_record(to_emails=("a@example.com", "b@example.com"))

        assert record.to_emails == ("a@example.com", "b@example.com")
        assert record.to_emails_count is None

    def test_recipient_list_over_cap_is_truncated_with_count(self) -> None:
        addresses = tuple(f"user{i}@example.com" for i in range(5))
        record = _email_record(to_emails=addresses, cc_emails=addresses)

        assert record.to_emails == addresses[:3]
        assert record.to_emails_count == 5
        assert record.cc_emails == addresses[:3]
        assert record.cc_emails_count == 5

    def test_occurred_at_is_a_full_timestamp(self) -> None:
        sent = datetime(2026, 3, 4, 8, 15, tzinfo=UTC)
        record = _email_record(sent_timestamp=sent)

        assert record.occurred_at == sent

    def test_carries_type_email_and_activity_id(self) -> None:
        record = _email_record(item_id="email_42")

        assert record.type == "email"
        assert record.activity_id == "email_42"


class TestActivityHistoryResolvedResponse:
    def test_accepts_groups_and_has_no_flat_records_or_cursor(self) -> None:
        record: TimelineRecord = _activity_record()
        group: ActivityGroupResponse[TimelineRecord] = ActivityGroupResponse(
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
        resolved = ResolvedPartyAsOfResponse.from_party(
            ResolvedPartyDto(id="1", search_type="people", name="Ada"),
            attributes=ProvenanceAttributes.model_validate(
                {"modifiedTimestamp": "2024-01-01", "modifiedBy": "alice"}
            ),
        )

        assert resolved == ResolvedPartyAsOfResponse(
            id="1",
            search_type="people",
            name="Ada",
            as_of=AsOfResponse(modified_timestamp="2024-01-01", modified_by="alice"),
        )
