import { createMeta } from '@unique-ag/mcp-server-module';
import { CALENDAR_TOOL_FORMAT_INFORMATION } from './utils/calendar-tool-format';

export const META = createMeta({
  icon: 'calendar',
  systemPrompt: `Check free/busy for people, distribution lists, or rooms via Outlook getSchedule.

Prefer dateRange.rangeType "relative" with a documented range. Weeks start Monday. The window must be shorter than 62 days — do not use thisYear, nextYear, lastYear, or next90Days. At most 20 SMTP addresses. Only attendees are checked. Include the signed-in user in attendees when they want to attend; get their SMTP from list_calendars ownerEmail on a calendar with isOwn true (prefer isDefaultCalendar true).

Subject and location on items appear only when the caller has detail-level permission. When isPrivate is true, treat details as redacted — do not invent a subject.

If availabilityNotes is present, display it after the results. If a relative range was used, state resolvedWindow.interpretation. If consentRequired is true, ask the user to reconnect Outlook. Do not invent free/busy data.

When the user asks what meetings another person has, or to look in that person's calendar, use list_calendars first. If no calendar has that ownerEmail (isOwn false), this tool is the fallback: you can see free/busy, not their event titles. Do not search isOwn true calendars and present those as theirs.`,
  toolFormatInformation: CALENDAR_TOOL_FORMAT_INFORMATION,
});
