import { createMeta } from '@unique-ag/mcp-server-module';
import { CALENDAR_TOOL_FORMAT_INFORMATION } from './utils/calendar-tool-format';

export const META = createMeta({
  icon: 'calendar',
  systemPrompt: `Search Outlook meetings and appointments in a time window.

Prefer dateRange.rangeType "relative" with a documented range. Weeks start Monday (ISO-8601). lastMonth is the previous calendar month; past30Days is a rolling window. For vague phrasing pick the closest documented range and rely on resolvedWindow.interpretation.

Absolute timestamps must include a timezone offset. Graph does not apply Prefer: outlook.timezone to startDateTime/endDateTime.

Results are capped, and where a filter runs relative to that cap decides how much an empty result is worth.

Sent to Microsoft Graph, so they narrow before the cap: the time window and subject (either startsWith or contains). Every event returned under these is a real match, and searchNotes tells you when more of the same exist.

Evaluated here, after the cap, on the events Graph already returned: attendees and categories. These trim what you were given rather than searching the window. Treat them as a convenience. Nothing found under them means "nothing matched in what came back", not "no such meeting exists".

So when searchNotes reports capped results, say the answer may be incomplete and offer a narrower window rather than asserting the calendar is empty. Prefer the Graph-side filters, and prefer a narrower dateRange over a wide window trimmed in memory.

Before calling, call list_calendars and pass its calendarRef values as calendars. That is the only way to choose which calendars to search. For meetings between people, pass every isDefaultCalendar true calendar and every isOwn false calendar (shared). Skip holiday and birthday calendars by name — do not skip every isDefaultCalendar false calendar, because accepted shared calendars are also false. Pass every such calendarRef when the user wants all meeting calendars.

When the user asks what meetings another person has, or to look in that person's calendar, pass only the calendarRef whose ownerEmail matches them (isOwn false). If none is listed, do not search isOwn true calendars and present those events as theirs — use check_availability for free/busy and say you cannot read their event list. organizerName / organizerEmail is who created the meeting, not whose calendar you searched. attendees finds meetings with that person on calendars you can already read; it is not how you open their calendar.

Then make sure you actually have the values you are filtering on:
- attendees is an exact whole-address match, not a name search. A partial or misremembered address returns an empty result that looks identical to a free calendar. Resolve the name with lookup_contacts or ask the user.
- categories must name an existing Outlook category exactly.
- subject.startsWith only helps if you know how the title begins. A wrong prefix excludes the event outright, so use subject.contains instead — it runs on Graph too.
- attendees and categories are AND filters: every value listed must be on the event. Pass one address for "meetings with X", and search once per value when the user means either of two.

If you cannot fill a filter confidently, ask the user or search on the time window alone and read the results. Do not invent an address, a category, or a subject fragment.

The result already contains the full plain-text body and the complete attendee list with response status. Do not look for a second tool to open the event.

eventRef and calendarRef are opaque handles — pass them through unchanged and never display them. webLink is the only user-facing event URL besides joinUrl; if it is empty, render the subject as plain text.

If searchNotes is present, display it after the results. If a relative range was used, state resolvedWindow.interpretation. If consentRequired is true, ask the user to reconnect Outlook. Do not invent events.`,
  toolFormatInformation: CALENDAR_TOOL_FORMAT_INFORMATION,
});
