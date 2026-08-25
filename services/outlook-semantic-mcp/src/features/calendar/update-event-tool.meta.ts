import { createMeta } from '@unique-ag/mcp-server-module';
import { CALENDAR_TOOL_FORMAT_INFORMATION } from './utils/calendar-tool-format';

export const META = createMeta({
  icon: 'calendar',
  systemPrompt: `Update an existing Outlook calendar event.

Pass eventRef from search_calendar_events without modification. There is no draft — attendees are notified immediately after the user confirms. For a recurring meeting the user chooses this occurrence or the whole series in the confirmation.

Do not display eventRef, eventId, calendarId, or accessPath. If consentRequired is true, ask the user to reconnect Outlook.`,
  toolFormatInformation: CALENDAR_TOOL_FORMAT_INFORMATION,
});
