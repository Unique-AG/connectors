import { createMeta } from '@unique-ag/mcp-server-module';
import { CALENDAR_TOOL_FORMAT_INFORMATION } from './utils/calendar-tool-format';

export const META = createMeta({
  icon: 'calendar',
  systemPrompt: `Search Outlook meetings and appointments in a time window.

Prefer dateRange.rangeType "relative" with a documented range. Weeks start Monday (ISO-8601). lastMonth is the previous calendar month; past30Days is a rolling window. For vague phrasing pick the closest documented range and rely on resolvedWindow.interpretation.

Absolute timestamps must include a timezone offset. Graph does not apply Prefer: outlook.timezone to startDateTime/endDateTime.

The result already contains the full plain-text body and the complete attendee list with response status. Do not look for a second tool to open the event.

eventRef, eventId, calendarId and accessPath are internal — never display them. webLink is the only user-facing event URL besides joinUrl; if it is empty, render the subject as plain text.

If searchNotes is present, display it after the results. If a relative range was used, state resolvedWindow.interpretation. If consentRequired is true, ask the user to reconnect Outlook. Do not invent events.`,
  toolFormatInformation: CALENDAR_TOOL_FORMAT_INFORMATION,
});
