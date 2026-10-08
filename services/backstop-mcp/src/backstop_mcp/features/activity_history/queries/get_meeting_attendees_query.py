"""Attendee list for one meeting or call: `GET /meeting-or-calls/{id}/attendees`.

Detail and history both use this query.
"""

import logging
from urllib.parse import quote

from opentelemetry import trace

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.features.activity_history.api_responses import AttendeeAttributes
from backstop_mcp.features.activity_history.internal_dto import AttendeeDto

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)


class GetMeetingAttendeesQuery:
    """Structured attendees for one meeting or call. A failed fetch raises."""

    def __init__(self, *, client: BackstopClient) -> None:
        self._client: BackstopClient = client

    async def run(self, *, resource_id: str) -> tuple[AttendeeDto, ...]:
        with _tracer.start_as_current_span("activity_history.query.meeting_attendees") as span:
            span.set_attribute("resource_id", resource_id)
            logger.debug("activity_history.attendees.fetch", extra={"resource_id": resource_id})
            page = await self._client.paginate(
                f"/meeting-or-calls/{quote(resource_id, safe='')}/attendees",
                params={"fields": "name,firstName,lastName,companyName,jobTitle"},
                schema=BackstopApiResource[AttendeeAttributes],
                max_records=None,
            )
            attendees = tuple(
                AttendeeDto(
                    id=resource.id,
                    name=resource.attributes.display_name(),
                    company_name=self._text(resource.attributes.company_name),
                    job_title=self._text(resource.attributes.job_title),
                )
                for resource in page.items
            )
            span.set_attribute("count", len(attendees))
            nameless = sum(1 for attendee in attendees if not attendee.name)
            if nameless:
                logger.debug(
                    "activity_history.attendees.nameless",
                    extra={
                        "resource_id": resource_id,
                        "nameless": nameless,
                        "total": len(attendees),
                    },
                )
            logger.info(
                "activity_history.attendees.fetched",
                extra={"resource_id": resource_id, "count": len(attendees)},
            )
            return attendees

    @staticmethod
    def _text(value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None
