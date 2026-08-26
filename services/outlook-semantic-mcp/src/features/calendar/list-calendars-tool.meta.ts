import { createMeta } from '@unique-ag/mcp-server-module';
import { CALENDAR_TOOL_FORMAT_INFORMATION } from './utils/calendar-tool-format';

export const META = createMeta({
  icon: 'calendar',
  systemPrompt: `Lists Outlook calendars the signed-in user can access: their own calendars, calendars shared with them, and calendars of mailboxes they have Full Access to.

Use this when the user asks which calendars they have, who a calendar belongs to, or whether they can edit a calendar. Always call this before search_calendar_events. calendarRef is an opaque handle: pass it to search_calendar_events as calendars, or to create_event unchanged, and never display or disassemble it.

The list can include holiday and birthday calendars. Those have isDefaultCalendar false and are not meeting calendars. Primary calendars (isDefaultCalendar true) are listed first: when calling search_calendar_events for meetings between people, pass only those.

ownerEmail on a calendar with isOwn true is the signed-in user SMTP. Use it in check_availability and suggest_meeting_times attendees when they want to attend.

A calendar with isOwn: false and canEdit: true is typically a delegated or shared calendar the user can create meetings on. canViewPrivateItems: false means private events on that calendar will be redacted.

If listNotes is present, display those notes after the table — they explain Full Access mailboxes that could not be listed.

If consentRequired is true, the user must reconnect Outlook to grant calendar permission. Do not invent calendar data.`,
  toolFormatInformation: CALENDAR_TOOL_FORMAT_INFORMATION,
});
