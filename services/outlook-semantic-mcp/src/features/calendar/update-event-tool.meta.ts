import { createMeta } from '@unique-ag/mcp-server-module';
import { CALENDAR_TOOL_FORMAT_INFORMATION } from './utils/calendar-tool-format';

export const META = createMeta({
  icon: 'calendar',
  systemPrompt: `Update an existing Outlook calendar event.

Pass eventRef from search_calendar_events without modification. There is no draft — attendees are notified immediately after the user confirms. For a recurring meeting the user chooses this occurrence or the whole series in the confirmation. Write body as HTML, not Markdown: <p>, <br>, <strong>, <em>, lists, and links. Send a fragment with no html/head/body wrappers. Do not include the Teams join section — this tool keeps Microsoft's existing join HTML. The HTML is sent to Outlook unchanged.

Do not display eventRef, calendarRef, eventId, or calendarId. If consentRequired is true, ask the user to reconnect Outlook.`,
  toolFormatInformation: CALENDAR_TOOL_FORMAT_INFORMATION,
});
