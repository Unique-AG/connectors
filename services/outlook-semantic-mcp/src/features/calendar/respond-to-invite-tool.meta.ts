import { createMeta } from '@unique-ag/mcp-server-module';
import { CALENDAR_TOOL_FORMAT_INFORMATION } from './utils/calendar-tool-format';

export const META = createMeta({
  icon: 'calendar',
  systemPrompt: `Respond to an Outlook meeting invitation (accept, tentatively accept, or decline).

Pass eventRef from search_calendar_events without modification. A confirmation is shown before the organizer is notified. Do not invent an eventRef. Do not display eventRef, calendarRef, eventId, or calendarId.

If consentRequired is true, ask the user to reconnect Outlook.`,
  toolFormatInformation: CALENDAR_TOOL_FORMAT_INFORMATION,
});
