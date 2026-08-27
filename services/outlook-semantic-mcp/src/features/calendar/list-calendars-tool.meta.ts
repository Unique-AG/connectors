import { createMeta } from '@unique-ag/mcp-server-module';
import { CALENDAR_TOOL_FORMAT_INFORMATION } from './utils/calendar-tool-format';

export const META = createMeta({
  icon: 'calendar',
  systemPrompt: `Lists Outlook calendars the signed-in user can access: their own calendars and calendars shared with them.

Use this when the user asks which calendars they have, who a calendar belongs to, or whether they can edit a calendar. Always call this before search_calendar_events. calendarRef is an opaque handle: pass it to search_calendar_events as calendars, or to create_event unchanged, and never display or disassemble it.

The list can include holiday and birthday calendars. Skip those by name — they are not meeting calendars. isDefaultCalendar false is not enough to skip: a calendar shared with the user (isOwn false) is listed under their own account with isDefaultCalendar false and still holds meetings. Primary calendars (isDefaultCalendar true) are listed first. When calling search_calendar_events for meetings between people, pass every isDefaultCalendar true calendar and every isOwn false calendar.

When the user asks what meetings another person has, or to look in that person's calendar, pick the calendar whose ownerEmail matches them (isOwn false). If none is listed, you cannot read their events — use check_availability for free/busy and say so. Do not search isOwn true calendars and present those as theirs.

ownerEmail on a calendar with isOwn true is the signed-in user SMTP. Use it in check_availability and suggest_meeting_times attendees when they want to attend.

A calendar with isOwn: false and canEdit: true is typically a shared calendar the user can create meetings on. canViewPrivateItems: false means private events on that calendar will be redacted.

If consentRequired is true, the user must reconnect Outlook to grant calendar permission. Do not invent calendar data.`,
  toolFormatInformation: CALENDAR_TOOL_FORMAT_INFORMATION,
});
